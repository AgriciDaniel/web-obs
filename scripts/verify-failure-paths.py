#!/usr/bin/env python3
"""Failure-path coverage: the engine must finish cleanly, or fail with a readable error, on hostile sites.

Runs the real crawler as a subprocess against local misbehaving servers (loopback only).
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get('WEB_OBS_PYTHON_BIN') or sys.executable

HOME = b'<html><head><title>Home</title></head><body><h1>Home</h1><p>Welcome to a test page with enough words to be useful.</p><a href="/ok">ok</a> <a href="/boom">boom</a> <a href="/reset">reset</a> <a href="/missing">missing</a></body></html>'
OK = b'<html><head><title>OK</title></head><body><h1>OK</h1><p>Healthy page body text goes here for the extractor.</p></body></html>'


class Site(BaseHTTPRequestHandler):
    scenario = 'robots-500'

    def log_message(self, *_args):
        pass

    def _send(self, code, body=b'', ctype='text/html; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split('?')[0]
        scenario = Site.scenario
        if path == '/robots.txt':
            if scenario == 'robots-500':
                return self._send(500, b'oops', 'text/plain')
            if scenario == 'robots-garbage':
                return self._send(200, bytes(range(1, 255)) * 40, 'text/plain')
            if scenario == 'huge-sitemap':
                return self._send(200, f'Sitemap: http://{self.headers["Host"]}/sitemap.xml\n'.encode(), 'text/plain')
            return self._send(404, b'', 'text/plain')
        if path == '/sitemap.xml':
            if scenario == 'huge-sitemap':
                urls = ''.join(f'<url><loc>http://{self.headers["Host"]}/p{i}</loc></url>' for i in range(6500))
                return self._send(200, f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'.encode(), 'application/xml')
            if scenario == 'broken-sitemap':
                return self._send(200, b'<urlset><url><loc>http://x/</loc>', 'application/xml')
            return self._send(404, b'', 'text/plain')
        if path == '/boom':
            return self._send(500, b'<html><body>server error</body></html>')
        if path == '/reset':
            # Close the socket without a valid HTTP response.
            self.connection.close()
            self.close_connection = True
            return
        if path in ('/', ''):
            return self._send(200, HOME)
        if path == '/ok' or path.startswith('/p'):
            return self._send(200, OK)
        return self._send(404, b'<html><body>not found</body></html>')


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # A cancelled capture hangs up mid-reply; that is the point of those tests, not an error.
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


class FailurePaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = QuietServer(('127.0.0.1', 0), Site)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def crawl(self, scenario, extra=(), timeout=120, target=None):
        Site.scenario = scenario
        with tempfile.TemporaryDirectory() as vault:
            Path(vault, '.obsidian').mkdir()
            env = {**os.environ, 'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{self.port}'}
            proc = subprocess.run(
                [PYTHON, str(ROOT / 'engine' / 'crawl_site.py'), target or f'http://127.0.0.1:{self.port}', '--vault', vault,
                 '--max-pages', '8', '--no-check-external', '--render', 'never', '--delay', '0', *extra],
                capture_output=True, text=True, timeout=timeout, env=env,
            )
            events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith('{')]
            graphs = list(Path(vault).glob('sites/*/_site-graph.json'))
            manifest = json.loads(graphs[0].read_text(encoding='utf-8')) if graphs else None
            return proc, events, manifest

    def assertFinishedCleanly(self, proc, events):
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertEqual(events[-1]['event'], 'complete', events[-1])
        for line in proc.stdout.splitlines():
            if line.strip():
                json.loads(line)  # the stream stays parseable JSON lines

    def test_robots_500_is_treated_as_disallow_and_still_completes(self):
        proc, events, manifest = self.crawl('robots-500')
        self.assertFinishedCleanly(proc, events)
        self.assertIsNotNone(manifest)
        # RFC 9309: an unreachable robots.txt (5xx) means assume complete disallow. The capture must say so, not crawl.
        policy = manifest['robotsPolicy']
        self.assertFalse(policy['canCrawl'], policy)
        self.assertEqual(manifest['stats']['pagesCrawled'], 0)

    def test_failing_pages_do_not_abort_the_capture(self):
        proc, events, manifest = self.crawl('robots-404')
        self.assertFinishedCleanly(proc, events)
        # /boom is a 500, /reset drops the connection, /missing is a 404. The healthy pages must still be captured.
        self.assertGreaterEqual(manifest['stats']['pagesCrawled'], 2)
        self.assertTrue(manifest['robotsPolicy']['canCrawl'])

    def test_binary_garbage_robots_does_not_crash(self):
        proc, events, manifest = self.crawl('robots-garbage')
        self.assertFinishedCleanly(proc, events)
        self.assertIsNotNone(manifest)

    def test_malformed_sitemap_does_not_crash(self):
        proc, events, manifest = self.crawl('broken-sitemap')
        self.assertFinishedCleanly(proc, events)
        self.assertGreaterEqual(manifest['stats']['pagesCrawled'], 1)

    def test_sitemap_over_the_url_cap_is_bounded(self):
        started = time.time()
        proc, events, manifest = self.crawl('huge-sitemap')
        self.assertFinishedCleanly(proc, events)
        self.assertLessEqual(manifest['stats']['pagesCrawled'], 8)
        self.assertLessEqual(manifest['stats']['sitemapUrlsTotal'], 5000)
        self.assertLess(time.time() - started, 90)

    def test_unreachable_target_fails_readably(self):
        Site.scenario = 'robots-500'
        with tempfile.TemporaryDirectory() as vault:
            Path(vault, '.obsidian').mkdir()
            proc = subprocess.run(
                [PYTHON, str(ROOT / 'engine' / 'crawl_site.py'), 'http://127.0.0.1:9', '--vault', vault, '--max-pages', '3', '--render', 'never'],
                capture_output=True, text=True, timeout=60,
            )
            lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith('{')]
            self.assertTrue(lines, 'engine must emit structured events')
            terminal = lines[-1]
            self.assertIn(terminal['event'], ('error', 'complete'))
            if terminal['event'] == 'error':
                self.assertTrue(terminal['message'])
                self.assertNotIn('Traceback', terminal['message'])
            self.assertNotIn('Traceback', proc.stdout)

    def test_missing_vault_is_a_clear_error(self):
        proc = subprocess.run([PYTHON, str(ROOT / 'engine' / 'crawl_site.py'), 'example.com', '--vault', '/nonexistent/web-obs-vault'],
                              capture_output=True, text=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        event = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(event['event'], 'error')
        self.assertIn('Vault directory does not exist', event['message'])

    def cancel_mid_capture(self, stop, *extra):
        """Start a slow capture, stop it after its first event, and check it ended as a cancel."""
        Site.scenario = 'huge-sitemap'
        with tempfile.TemporaryDirectory() as vault:
            Path(vault, '.obsidian').mkdir()
            env = {**os.environ, 'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{self.port}'}
            proc = subprocess.Popen(
                [PYTHON, str(ROOT / 'engine' / 'crawl_site.py'), f'http://127.0.0.1:{self.port}', '--vault', vault,
                 '--max-pages', '8', '--render', 'never', '--delay', '2', *extra],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            )
            first = proc.stdout.readline()
            self.assertIn('"start"', first)
            started = time.monotonic()
            stop(proc)
            out, err = proc.communicate(timeout=30)
            self.assertNotIn('Traceback', err)
            self.assertIn('"cancelled"', first + out)
            self.assertLess(time.monotonic() - started, 20, 'the cancel must not wait for the capture to end')
            self.assertFalse(Path(vault, 'sites').exists() and any(Path(vault, 'sites').iterdir()),
                             'a cancelled capture publishes nothing')
            return proc.returncode

    @unittest.skipIf(os.name == 'nt', 'Windows has no SIGTERM; the standard input tests cover cancelling there')
    def test_sigterm_cancels_without_a_traceback(self):
        code = self.cancel_mid_capture(lambda proc: proc.send_signal(signal.SIGTERM))
        self.assertIn(code, (130, -signal.SIGTERM))

    def test_cancel_line_on_standard_input_cancels_on_every_system(self):
        def stop(proc):
            proc.stdin.write('cancel\n')
            proc.stdin.flush()
        self.assertEqual(self.cancel_mid_capture(stop, '--cancel-on-stdin'), 130)

    def test_closed_standard_input_cancels_when_the_parent_goes_away(self):
        self.assertEqual(self.cancel_mid_capture(lambda proc: proc.stdin.close(), '--cancel-on-stdin'), 130)


PROMOTION_PROBE = r'''
import signal, sys, time
sys.path.insert(0, sys.argv[1])
import cancel_channel, capture_store
def stop(_signum, _frame):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, stop)
cancel_channel.listen()
try:
    with capture_store.promotion_signals():
        print('renaming', flush=True)
        time.sleep(1)
        print('renames finished', flush=True)
    time.sleep(5)
except KeyboardInterrupt:
    print('cancelled', flush=True)
'''


class PromotionWithCancelReader(unittest.TestCase):
    """The standard input reader must not take a signal the main thread is holding back."""

    @unittest.skipIf(os.name == 'nt', 'Windows has no signal mask; PromotionWithoutSignalMask covers it')
    def test_a_cancel_during_promotion_waits_for_the_renames(self):
        for stop in ('close input', 'sigterm'):
            with self.subTest(stop):
                proc = subprocess.Popen([PYTHON, '-c', PROMOTION_PROBE, str(ROOT / 'engine')], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertEqual(proc.stdout.readline().strip(), 'renaming')
                if stop == 'close input':
                    proc.stdin.close()
                else:
                    proc.send_signal(signal.SIGTERM)
                out, err = proc.communicate(timeout=20)
                self.assertEqual(out.split(), ['renames', 'finished', 'cancelled'], err)


class PromotionWithoutSignalMask(unittest.TestCase):
    """Windows has no signal mask; a cancel during the two folder renames waits until they are done."""

    def test_a_cancel_during_promotion_is_delivered_after_it(self):
        sys.path.insert(0, str(ROOT / 'engine'))
        import types
        from unittest.mock import patch
        import capture_store
        no_mask = types.SimpleNamespace(**{name: getattr(signal, name) for name in dir(signal) if name != 'pthread_sigmask'})
        steps = []
        with patch.object(capture_store, 'signal', no_mask):
            with self.assertRaises(KeyboardInterrupt):
                with capture_store.promotion_signals():
                    signal.raise_signal(signal.SIGINT)
                    time.sleep(0.05)
                    steps.append('renames finished')
        self.assertEqual(steps, ['renames finished'])
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)


if __name__ == '__main__':
    unittest.main(verbosity=1)
