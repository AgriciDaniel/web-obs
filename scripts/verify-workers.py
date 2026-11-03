#!/usr/bin/env python3
"""Isolated local fixtures for process workers, deadlines, TLS and page policies."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from page_fetch import MAX_HTML_BYTES, PageFetcher
from site_intel import build_robots_policy
from url_safety import safe_requests_session
from workers import TaskDeadlineExceeded, WorkerDispatcher, WorkerError, origin_key


class Fixture(BaseHTTPRequestHandler):
    lock = threading.Lock()
    active = 0
    peak = 0
    hits = []
    robots_body = 'User-agent: WebObs\nAllow: /\n'
    transport_port = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def do_HEAD(self):
        self.respond(True)

    def do_GET(self):
        self.respond(False)

    def respond(self, head):
        with self.lock:
            Fixture.active += 1
            Fixture.peak = max(Fixture.peak, Fixture.active)
            Fixture.hits.append((self.path, time.monotonic()))
        try:
            if self.path.startswith('/hold'):
                time.sleep(.2)
            body = b'<html><head><title>Local page</title></head><body>Local content.</body></html>'
            if self.path == '/robots.txt':
                body = self.robots_body.encode()
            if self.path == '/spinner':
                body = b'<html><body><script>while(true){}</script></body></html>'
            if self.path == '/transports':
                body = f'''<html><body><div id="root"></div><p id="frame"></p><p id="worker"></p><p id="shared-worker"></p>
                <script>
                addEventListener('message', event => {{ if(event.data==='frame guarded') document.getElementById('frame').textContent=event.data; }});
                try {{
                  const connection=new RTCPeerConnection({{iceServers:[{{urls:'stun:127.0.0.1:{self.transport_port}'}}]}});
                  connection.createDataChannel('probe');
                  connection.createOffer().then(offer=>connection.setLocalDescription(offer)).catch(()=>{{}});
                }} catch(error) {{}}
                try {{ new webkitRTCPeerConnection(); }} catch(error) {{}}
                try {{ new WebTransport('https://127.0.0.1:{self.transport_port}/'); }} catch(error) {{}}
                try {{ Object.defineProperty(window,'RTCPeerConnection',{{value:function(){{}}}}); }} catch(error) {{}}
                const guarded = Object.getOwnPropertyDescriptor(window,'RTCPeerConnection').configurable === false;
                document.getElementById('root').innerHTML='<h1>SPA content rendered</h1><p>guards:'+guarded+'</p>';
                try {{ const worker=new Worker(URL.createObjectURL(new Blob([
                  "postMessage('attempted');try{{const transport=new WebTransport('https://127.0.0.1:{self.transport_port}/');transport.ready.then(()=>postMessage('connected')).catch(()=>postMessage('blocked'));}}catch(error){{postMessage('blocked');}}"
                ],{{type:'text/javascript'}})));
                worker.onmessage=event=>{{document.getElementById('worker').textContent='worker:'+event.data;}};
                }} catch(error) {{ document.getElementById('worker').textContent='worker:blocked'; }}
                try {{ new SharedWorker(URL.createObjectURL(new Blob(["new WebTransport('https://127.0.0.1:{self.transport_port}/');"],{{type:'text/javascript'}}))); }}
                catch(error) {{ document.getElementById('shared-worker').textContent='shared-worker:blocked'; }}
                </script><iframe src="/transport-frame"></iframe></body></html>'''.encode()
            if self.path == '/transport-frame':
                body = f'''<html><body><script>
                try {{
                  const connection=new RTCPeerConnection({{iceServers:[{{urls:'stun:127.0.0.1:{self.transport_port}'}}]}});
                  connection.createDataChannel('frame-probe');
                  connection.createOffer().then(offer=>connection.setLocalDescription(offer)).catch(()=>{{}});
                }} catch(error) {{ parent.postMessage('frame guarded','*'); }}
                </script></body></html>'''.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf' if self.path == '/pdf' else 'text/plain' if self.path == '/robots.txt' else 'text/html')
            self.send_header('Content-Length', str(10000 if self.path == '/drip' else len(body)))
            self.end_headers()
            if not head:
                if self.path == '/drip':
                    for _ in range(10000):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(.005)
                else:
                    self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        finally:
            with self.lock:
                Fixture.active -= 1


class LocalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.environment = patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{cls.server.server_port}', 'CLAUDE_SEO_LOCAL_TARGETS': ''})
        cls.environment.start()

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def payload(self, path='/'):
        return {'url': self.origin + path, 'target_host': '127.0.0.1',
                'robots_policies': {self.origin: build_robots_policy('', 200)}}

    def wait_active(self, dispatcher):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if dispatcher.stats()['active']:
                return
            time.sleep(.01)
        self.fail('Worker did not acquire a request lease.')

    def test_numeric_pin_allows_overlapping_requests_without_global_dns_patch(self):
        original = socket.getaddrinfo
        outputs = []
        def fetch():
            with safe_requests_session(self.origin + '/hold') as session:
                response = session.get(self.origin + '/hold', timeout=2, stream=True)
                outputs.append(response.content)
        first, second = threading.Thread(target=fetch), threading.Thread(target=fetch)
        first.start(); second.start(); first.join(4); second.join(4)
        self.assertEqual(len(outputs), 2)
        self.assertIs(socket.getaddrinfo, original)

    def test_process_jobs_overlap_and_worker_is_reused(self):
        Fixture.peak = 0
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            jobs = [dispatcher.submit('page-http', self.payload('/hold/' + str(i)), timeout_sec=8) for i in range(3)]
            for job in jobs:
                self.assertEqual(job.result(12)['state'], 'complete')
            first = set(dispatcher.stats()['workerPids'])
            self.assertEqual(dispatcher.submit('page-http', self.payload(), 5).result(8)['state'], 'complete')
            self.assertEqual(set(dispatcher.stats()['workerPids']), first)
            self.assertGreaterEqual(Fixture.peak, 2)
            self.assertLessEqual(dispatcher.stats()['origins'][self.origin], 2)
            self.assertEqual(dispatcher.stats()['active'], 0)

    def test_startup_failures_settle_future_close_partials_and_keep_supervisor_alive(self):
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            # Reproduce the reviewer's direct startup failure.
            with patch.object(dispatcher, '_start_slot', side_effect=OSError('Injected startup failure')):
                failed = dispatcher.submit('page-http', self.payload(), 4)
                with self.assertRaisesRegex(WorkerError, 'Could not start page-http worker'):
                    failed.result(3)
            self.assertTrue(dispatcher.supervisor.is_alive())
            self.assertEqual(dispatcher.stats()['pending'], 0)
            self.assertEqual(dispatcher.submit('page-http', self.payload(), 6).result(9)['state'], 'complete')

            # Fail Process.start after real pipe endpoints have been allocated.
            connections = []
            original_pipe = dispatcher.context.Pipe
            def pipe(*args, **kwargs):
                pair = original_pipe(*args, **kwargs)
                connections.extend(pair)
                return pair
            def fail_start():
                raise OSError('Injected process creation failure')
            with patch.object(dispatcher.context, 'Pipe', side_effect=pipe), \
                 patch.object(dispatcher.context, 'Process', return_value=SimpleNamespace(pid=None, start=fail_start)):
                failed = dispatcher.submit('asset', self.payload(), 4)
                with self.assertRaisesRegex(WorkerError, 'process creation failure'):
                    failed.result(3)
            self.assertTrue(all(connection.closed for connection in connections))
            self.assertTrue(dispatcher.supervisor.is_alive())
            self.assertTrue(dispatcher.submit('asset', self.payload(), 6).result(9)['raw_bytes'])

            # Fail a supervisor IPC thread after a real child has already started.
            processes = []
            original_process = dispatcher.context.Process
            original_start = threading.Thread.start
            def process(*args, **kwargs):
                child = original_process(*args, **kwargs)
                processes.append(child)
                return child
            def start(thread):
                if thread.name == 'web-obs-task-writer':
                    raise RuntimeError('Injected IPC thread startup failure')
                return original_start(thread)
            with patch.object(dispatcher.context, 'Process', side_effect=process), \
                 patch.object(threading.Thread, 'start', start):
                failed = dispatcher.submit('link', self.payload(), 4)
                with self.assertRaisesRegex(WorkerError, 'IPC thread startup failure'):
                    failed.result(4)
            self.assertTrue(processes)
            self.assertTrue(all(child._closed or not child.is_alive() for child in processes))
            self.assertTrue(dispatcher.supervisor.is_alive())
            self.assertEqual(dispatcher.stats()['active'], 0)
            self.assertEqual(dispatcher.submit('link', self.payload(), 6).result(9)['status'], 'ok')

    def test_shared_broker_global_origin_limits_and_recovery(self):
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            broker = dispatcher.limiter
            tokens = [broker.try_acquire('fixture', f'https://host{i // 2}.example/') for i in range(6)]
            self.assertTrue(all(tokens))
            self.assertIsNone(broker.try_acquire('fixture', 'https://another.example/'))
            self.assertIsNone(broker.try_acquire('fixture', 'https://host0.example/'))
            self.assertEqual(broker.snapshot()['active'], 6)
            self.assertEqual(broker.recover('fixture'), 6)
            self.assertEqual(broker.snapshot()['active'], 0)

    def test_broker_paces_origin_request_starts(self):
        with WorkerDispatcher(min_interval_sec=.05) as dispatcher:
            broker = dispatcher.limiter
            token = broker.try_acquire('fixture', self.origin)
            self.assertTrue(token)
            broker.release(token)
            self.assertIsNone(broker.try_acquire('fixture', self.origin))
            time.sleep(.06)
            self.assertTrue(broker.try_acquire('fixture', self.origin))
            broker.recover('fixture')

    def test_absolute_task_deadline_stops_slow_drip_and_recovers_lease(self):
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            dispatcher.submit('page-http', self.payload(), 6).result(9)
            started = time.monotonic()
            future = dispatcher.submit('page-http', self.payload('/drip'), .2)
            with self.assertRaises(TaskDeadlineExceeded):
                future.result(4)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(dispatcher.stats()['active'], 0)
            self.assertEqual(dispatcher.submit('page-http', self.payload(), 6).result(9)['state'], 'complete')

    def test_cancellation_stops_owned_worker_and_recovers_lease(self):
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            future = dispatcher.submit('page-http', self.payload('/drip'), 10)
            self.wait_active(dispatcher)
            dispatcher.cancel_all()
            with self.assertRaises(CancelledError):
                future.result(2)
            self.assertEqual(dispatcher.stats()['active'], 0)
            self.assertEqual(dispatcher.stats()['running'], 0)
            self.assertEqual(dispatcher.submit('page-http', self.payload(), 6).result(9)['state'], 'complete')

    def test_cancelled_queued_future_never_dispatches(self):
        with WorkerDispatcher(max_inflight=1, min_interval_sec=0) as dispatcher:
            blocker = dispatcher.submit('page-http', self.payload('/hold'), 6)
            queued = dispatcher.submit('page-http', self.payload('/must-not-run'), 6)
            self.assertTrue(queued.cancel())
            blocker.result(9)
            self.assertNotIn('/must-not-run', [path for path, _ in Fixture.hits])

    def test_asset_and_link_operations_use_shared_dispatcher(self):
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            asset = dispatcher.submit('asset', self.payload(), 6)
            link = dispatcher.submit('link', self.payload(), 6)
            self.assertTrue(asset.result(9)['raw_bytes'])
            self.assertEqual(link.result(9)['status'], 'ok')
            self.assertLessEqual(dispatcher.stats()['peak'], 6)

    def test_nonhtml_headers_return_resource_before_reading_body(self):
        fetcher = PageFetcher()
        try:
            result = fetcher.fetch(self.origin + '/pdf', render_mode='never')
            self.assertEqual(result['state'], 'resource')
            self.assertEqual(result['resource_type'], 'document')
            self.assertEqual(result['raw_bytes'], b'')
            self.assertIsNone(result['error'])
        finally:
            fetcher.close()

    def test_parent_requests_join_same_limiter(self):
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            with dispatcher.parent_requests(timeout_sec=2):
                with safe_requests_session(self.origin) as session:
                    response = session.get(self.origin, timeout=1, stream=True)
                    self.assertEqual(dispatcher.stats()['active'], 1)
                    response.close()
                    self.assertEqual(dispatcher.stats()['active'], 0)

    def test_strict_host_policy_does_not_allow_cached_foreign_document(self):
        from workers import _policies
        payload = self.payload()
        payload['robots_policies']['https://foreign.example'] = build_robots_policy('', 200)
        page, resource = _policies(payload)
        self.assertFalse(page('https://foreign.example/'))
        self.assertTrue(resource('https://foreign.example/script.js'))

    def redirected_origin(self, robots_body, foreign=False):
        class Destination(Fixture):
            pass
        Destination.robots_body = robots_body
        destination = ThreadingHTTPServer(('127.0.0.1', 0), Destination)
        thread = threading.Thread(target=destination.serve_forever, daemon=True)
        thread.start()
        other_origin = f'http://{"localhost" if foreign else "127.0.0.1"}:{destination.server_port}'
        original = Fixture.respond
        def respond(handler, head):
            if handler.path == '/new-origin':
                handler.send_response(302)
                handler.send_header('Location', other_origin + '/destination')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
            else:
                original(handler, head)
        Fixture.hits.clear()
        try:
            targets = f'127.0.0.1:{self.server.server_port},127.0.0.1:{destination.server_port},localhost:{destination.server_port}'
            with patch.object(Fixture, 'respond', respond), patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS': targets}), WorkerDispatcher(min_interval_sec=0) as dispatcher:
                result = dispatcher.submit('page-http', self.payload('/new-origin'), 8).result(11)
            return result, other_origin, [path for path, _ in Fixture.hits]
        finally:
            destination.shutdown(); destination.server_close(); thread.join(2)

    def test_same_site_origin_redirect_fetches_own_robots_before_page(self):
        result, origin, hits = self.redirected_origin('User-agent: WebObs\nAllow: /\n')
        self.assertIsNone(result['error'], result['error'])
        self.assertEqual(result['final_url'], origin + '/destination')
        self.assertLess(hits.index('/robots.txt'), hits.index('/destination'))
        self.assertIn(origin, result['discovered_robots_policies'])
        self.assertIn(b'WebObs', result['robots_receipts'][origin]['raw_bytes'])

    def test_same_site_origin_redirect_cannot_ignore_destination_robots(self):
        result, origin, hits = self.redirected_origin('User-agent: WebObs\nDisallow: /\n')
        self.assertEqual(result['error_kind'], 'policy')
        self.assertIn('/robots.txt', hits)
        self.assertNotIn('/destination', hits)
        self.assertIn(origin, result['discovered_robots_policies'])

    def test_foreign_document_rejected_before_robots_or_document_fetch(self):
        result, origin, hits = self.redirected_origin('User-agent: WebObs\nAllow: /\n', foreign=True)
        self.assertEqual(result['error_kind'], 'policy')
        self.assertNotIn('/robots.txt', hits)
        self.assertNotIn('/destination', hits)
        self.assertNotIn(origin, result.get('discovered_robots_policies', {}))

    def test_link_redirect_to_robots_disallowed_path_never_fetches_target(self):
        original = Fixture.respond
        def respond(handler, head):
            if handler.path == '/policy-redirect':
                handler.send_response(302)
                handler.send_header('Location', '/private-link')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
            else:
                original(handler, head)
        payload = self.payload('/policy-redirect')
        payload['robots_policies'][self.origin] = build_robots_policy('User-agent: WebObs\nDisallow: /private-link', 200)
        with patch.object(Fixture, 'respond', respond), WorkerDispatcher(min_interval_sec=0) as dispatcher:
            result = dispatcher.submit('link', payload, 6).result(9)
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('/private-link', [path for path, _ in Fixture.hits])

    def test_real_browser_deadline_stops_owned_descendants(self):
        from browser_runtime import resolve_chromium_executable
        from playwright.sync_api import sync_playwright
        from workers import _process_tree, _same_process
        with sync_playwright() as playwright:
            if not resolve_chromium_executable(playwright)['executablePath']:
                self.skipTest('Matching Chromium is absent from this interpreter environment')
        with WorkerDispatcher(min_interval_sec=0) as dispatcher:
            warm = dispatcher.submit('render', self.payload(), 8).result(11)
            self.assertIsNone(warm['error'], warm['error'])
            owned = _process_tree(dispatcher.stats()['workerPids'][0])
            self.assertGreater(len(owned), 1)
            future = dispatcher.submit('render', self.payload('/spinner'), .25)
            with self.assertRaises(TaskDeadlineExceeded):
                future.result(4)
            for pid, started in owned.items():
                if _same_process(pid, started):
                    state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
                    self.assertEqual(state, 'Z', f'Owned browser process {pid} remains running')
            self.assertEqual(dispatcher.stats()['active'], 0)

    def test_real_browser_blocks_unrouted_transports_without_udp_while_spa_renders(self):
        from browser_runtime import resolve_chromium_executable
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            if not resolve_chromium_executable(playwright)['executablePath']:
                self.skipTest('Matching Chromium is absent from this interpreter environment')
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for attempt in range(10):
            listener.bind(('127.0.0.1', 0))
            try:
                tcp_listener.bind(listener.getsockname())
                break
            except OSError:
                listener.close()
                listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            listener.close()
            tcp_listener.close()
            self.fail('Could not reserve an isolated TCP/UDP transport fixture port')
        listener.settimeout(.5)
        tcp_listener.listen(2)
        tcp_listener.settimeout(.3)
        Fixture.transport_port = listener.getsockname()[1]
        fetcher = PageFetcher()
        try:
            result = fetcher.fetch(self.origin + '/transports', render_mode='always', timeout_sec=8)
            self.assertIsNone(result['error'], result['error'])
            self.assertTrue(result['render_used'])
            self.assertIn('SPA content rendered', result['html'])
            self.assertIn('guards:true', result['html'])
            self.assertIn('frame guarded', result['html'])
            self.assertIn('worker:blocked', result['html'])
            self.assertIn('shared-worker:blocked', result['html'])
            kinds = [row['resourceType'] for row in result['blocked_requests']]
            self.assertGreaterEqual(kinds.count('webrtc'), 2)
            self.assertIn('webtransport', kinds)
            worker_apis = {row.get('api') for row in result['blocked_requests'] if row['resourceType'] == 'worker'}
            self.assertEqual(worker_apis, {'Worker', 'SharedWorker'})
            with self.assertRaises(socket.timeout):
                listener.recvfrom(4096)
            with self.assertRaises(socket.timeout):
                tcp_listener.accept()
        finally:
            fetcher.close()
            listener.close()
            tcp_listener.close()
            Fixture.transport_port = None

    @unittest.skipUnless(shutil.which('openssl'), 'Local TLS fixture requires installed openssl')
    def test_pinned_https_preserves_original_certificate_hostname(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = Path(directory) / 'cert.pem', Path(directory) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                '-days', '1', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
            tls = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            tls.socket = context.wrap_socket(tls.socket, server_side=True)
            thread = threading.Thread(target=tls.serve_forever, daemon=True); thread.start()
            url = f'https://localhost:{tls.server_port}/'
            try:
                with patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS': f'localhost:{tls.server_port},127.0.0.1:{tls.server_port}'}):
                    with safe_requests_session(url) as session:
                        self.assertEqual(session.get(url, timeout=2, verify=str(cert)).status_code, 200)
                    bad = f'https://127.0.0.1:{tls.server_port}/'
                    import requests
                    with safe_requests_session(bad) as session:
                        with self.assertRaises(requests.exceptions.SSLError):
                            session.get(bad, timeout=2, verify=str(cert))
            finally:
                tls.shutdown(); tls.server_close(); thread.join(2)


class MockBrowserTests(unittest.TestCase):
    def test_unconfirmed_process_exit_is_an_error_not_cleanup_success(self):
        import workers
        process = SimpleNamespace(pid=987654, is_alive=lambda: True, kill=lambda: None, join=lambda **kwargs: None)
        with patch.object(workers, '_process_tree', return_value={987654: 1}), \
             patch.object(workers, '_same_process', return_value=True), \
             patch.object(workers.os, 'getpgid', return_value=987654), \
             patch.object(workers.os, 'killpg'), patch.object(workers.os, 'kill'), \
             patch.object(Path, 'read_text', return_value='987654 (fixture) R 0 0'):
            with self.assertRaisesRegex(workers.WorkerError, 'could not be confirmed'):
                workers._stop_owned(process)

    def run_browser(self, *, size=20, foreign=False, calls=1, prior_http=None):
        import page_fetch
        counts = {'starts': 0, 'launches': 0, 'contexts': 0, 'closedContexts': 0, 'browserClosed': 0}
        origin = 'https://capture.example/'
        class Page:
            url = origin
            def goto(self, *args, **kwargs):
                if foreign:
                    self.url = 'https://foreign.example/'
                return SimpleNamespace(status=200, headers={'content-type': 'text/html'})
            def evaluate(self, *_args): return size
            def content(self): return '<html>Local content</html>'
        class Context:
            def expose_binding(self, *_args): pass
            def add_init_script(self, **_kwargs): pass
            def route(self, pattern, handler): self.handler = handler
            def route_web_socket(self, *_args): pass
            def new_page(self): return Page()
            def close(self): counts['closedContexts'] += 1
        class Browser:
            def is_connected(self): return True
            def new_context(self, **kwargs): counts['contexts'] += 1; return Context()
            def close(self): counts['browserClosed'] += 1
        class Driver:
            def __init__(self): self.chromium = SimpleNamespace(launch=self.launch)
            def start(self): counts['starts'] += 1; return self
            def stop(self): pass
            def launch(self, **kwargs): counts['launches'] += 1; return Browser()
        with patch.object(page_fetch, 'sync_playwright', Driver), patch.object(page_fetch, 'resolve_chromium_executable', return_value={'executablePath': 'fixture', 'error': None}):
            fetcher = PageFetcher()
            try:
                results = [fetcher.fetch(origin, render_mode='always', allow_url=lambda u: u == origin, allow_resource_url=lambda u: True, prior_http=prior_http) for _ in range(calls)]
            finally:
                fetcher.close()
        return results, counts

    def test_browser_reused_with_fresh_contexts(self):
        results, counts = self.run_browser(calls=2)
        self.assertTrue(all(row['error'] is None for row in results))
        self.assertEqual(counts, {'starts': 1, 'launches': 1, 'contexts': 2, 'closedContexts': 2, 'browserClosed': 1})

    def test_final_navigation_cannot_use_asset_policy(self):
        results, counts = self.run_browser(foreign=True)
        self.assertEqual(results[0]['error_kind'], 'policy')
        self.assertFalse(results[0]['render_used'])
        self.assertEqual(counts['closedContexts'], 1)

    def test_rendered_dom_rejected_before_large_ipc_copy(self):
        results, counts = self.run_browser(size=MAX_HTML_BYTES + 1)
        self.assertEqual(results[0]['error_kind'], 'size')
        self.assertEqual(results[0]['raw_bytes'], b'')
        self.assertEqual(counts['closedContexts'], 1)

    def test_render_preserves_prior_http_redirect_receipt_without_mutating_it(self):
        prior = {'redirect_chain': [{'url': 'https://capture.example/before', 'status_code': 301}],
                 'final_url': 'https://capture.example/', 'blocked_requests': [], 'raw_kind': 'http-response-decoded'}
        results, _counts = self.run_browser(prior_http=prior)
        self.assertEqual(results[0]['redirect_chain'], prior['redirect_chain'])
        self.assertIsNot(results[0]['redirect_chain'], prior['redirect_chain'])
        self.assertEqual(results[0]['raw_kind'], 'rendered-dom')
        self.assertEqual(prior['raw_kind'], 'http-response-decoded')

    def test_document_route_has_strict_policy_before_http(self):
        import url_safety
        handler = url_safety.make_safe_playwright_route_handler(allow_url=lambda url: True, allow_document_url=lambda url: False)
        class Route:
            aborted = False
            def abort(self): self.aborted = True
        route = Route()
        request = SimpleNamespace(url='https://foreign.example/', resource_type='document', method='GET')
        with patch.object(url_safety, 'safe_requests_session', side_effect=AssertionError('No HTTP may happen')):
            handler(route, request)
        self.assertTrue(route.aborted)


if __name__ == '__main__':
    unittest.main(verbosity=2)
