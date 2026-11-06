#!/usr/bin/env python3
"""WebObs identifies itself honestly and slows down when a site asks it to.

Covers the user agent (one honest string, one version source, the same string from
requests and from the Playwright browser), Crawl-delay from robots.txt, and backing off
on HTTP 429 and 503 with Retry-After.
"""
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))

from site_intel import build_robots_policy  # noqa: E402
from url_safety import DEFAULT_REQUEST_HEADERS, DEFAULT_USER_AGENT, ENGINE_VERSION, retry_after_seconds  # noqa: E402


def page(title, links=()):
    anchors = ''.join(f'<a href="{href}">{href}</a> ' for href in links)
    return (f'<!doctype html><html lang="en"><head><title>{title}</title></head>'
            f'<body><main><h1>{title}</h1><p>{" ".join(["word"] * 80)}</p>{anchors}</main></body></html>').encode()


class Site(BaseHTTPRequestHandler):
    """robots: the robots.txt body. rate_limited: path -> how many 429s to send first (-1 = always)."""
    robots = 'User-agent: *\nAllow: /\n'
    pages = ('/a', '/b', '/c')
    rate_limited: dict = {}
    retry_after = '1'
    limit_status = 429
    hits: list = []

    def log_message(self, *_args):
        pass

    def send(self, status, body=b'', content_type='text/html; charset=utf-8', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        type(self).hits.append((time.monotonic(), path, self.headers.get('User-Agent')))
        if path == '/robots.txt':
            return self.send(200, self.robots.encode(), 'text/plain')
        if path == '/sitemap.xml':
            origin = f'http://127.0.0.1:{self.server.server_port}'
            urls = ''.join(f'<url><loc>{origin}{p}</loc></url>' for p in ('/', *self.pages))
            return self.send(200, f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'.encode(), 'application/xml')
        remaining = self.rate_limited.get(path, 0)
        if remaining:
            if remaining > 0:
                self.rate_limited[path] = remaining - 1
            return self.send(self.limit_status, b'Slow down', 'text/plain', {'Retry-After': self.retry_after} if self.retry_after else {})
        if path == '/':
            return self.send(200, page('Home', self.pages))
        if path in self.pages:
            return self.send(200, page(path.strip('/').upper(), ('/',)))
        self.send(404, b'Not found', 'text/plain')


def capture(handler, *extra):
    handler.hits = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port
    try:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            (vault / '.obsidian').mkdir()
            env = {**os.environ, 'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{port}'}
            completed = subprocess.run(
                [sys.executable, str(ROOT / 'engine' / 'crawl_site.py'), f'http://127.0.0.1:{port}', '--vault', str(vault),
                 '--max-pages', '10', '--no-check-external', '--delay', '0', '--no-browser-audit', '--no-dns-checks', *extra],
                env=env, capture_output=True, text=True, encoding='utf-8', timeout=240)
            if completed.returncode != 0:
                errors = [line for line in completed.stdout.splitlines() if '"event": "error"' in line]
                raise RuntimeError((completed.stderr or '\n'.join(errors) or completed.stdout)[-2000:])
            graph = json.loads((vault / 'sites' / f'127.0.0.1-{port}' / '_site-graph.json').read_text(encoding='utf-8'))
            return graph, list(handler.hits)
    finally:
        server.shutdown()


class IdentityTests(unittest.TestCase):
    def test_user_agent_is_an_honest_compatible_bot_string(self):
        self.assertRegex(DEFAULT_USER_AGENT, r'^Mozilla/5\.0 \(compatible; WebObs/\d+\.\d+\.\d+; \+https://\S+\)$')
        self.assertNotIn('Chrome/', DEFAULT_USER_AGENT, 'must not claim a browser version it is not')
        self.assertEqual(DEFAULT_REQUEST_HEADERS['User-Agent'], DEFAULT_USER_AGENT)
        self.assertIn('docs/CRAWLER.md', DEFAULT_USER_AGENT)
        self.assertTrue((ROOT / 'docs' / 'CRAWLER.md').is_file(), 'the page the user agent points to exists')

    def test_one_version_everywhere(self):
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
        manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))['version']
        versions = json.loads((ROOT / 'versions.json').read_text(encoding='utf-8'))
        self.assertEqual(ENGINE_VERSION, package)
        self.assertEqual(manifest, package)
        self.assertIn(package, versions)
        self.assertIn(f'WebObs/{package};', DEFAULT_USER_AGENT)

    def test_robots_product_token_still_matches_the_new_string(self):
        policy = build_robots_policy('User-agent: *\nDisallow: /\n\nUser-agent: WebObs\nDisallow: /private\n', 200)
        self.assertEqual(policy['matchedAgents'], ['webobs'])
        self.assertEqual(policy['productToken'], 'WebObs')


class PolitenessUnitTests(unittest.TestCase):
    def test_retry_after_seconds_and_dates(self):
        self.assertEqual(retry_after_seconds({'Retry-After': '7'}), 7.0)
        self.assertEqual(retry_after_seconds({'retry-after': ' 12 '}), 12.0)
        now = time.time()
        self.assertAlmostEqual(retry_after_seconds({'Retry-After': formatdate(now + 40, usegmt=True)}, now=now), 40, delta=1.5)
        self.assertEqual(retry_after_seconds({'Retry-After': formatdate(now - 40, usegmt=True)}, now=now), 0.0)
        self.assertEqual(retry_after_seconds({'Retry-After': 'soon'}, default=30), 30)
        self.assertEqual(retry_after_seconds({}, default=30), 30)

    def test_crawl_delay_follows_the_matching_group(self):
        self.assertEqual(build_robots_policy('User-agent: *\nCrawl-delay: 5\n', 200)['crawlDelaySec'], 5.0)
        self.assertEqual(build_robots_policy('User-agent: WebObs\nCrawl-delay: 2\n\nUser-agent: *\nCrawl-delay: 9\n', 200)['crawlDelaySec'], 2.0)
        self.assertIsNone(build_robots_policy('User-agent: WebObs\nAllow: /\n\nUser-agent: *\nCrawl-delay: 9\n', 200)['crawlDelaySec'],
                          'a WebObs group without Crawl-delay is not slowed by the * group')
        self.assertIsNone(build_robots_policy('User-agent: *\nCrawl-delay: never\n', 200)['crawlDelaySec'])
        self.assertIsNone(build_robots_policy('User-agent: *\nCrawl-delay: -3\n', 200)['crawlDelaySec'])
        self.assertIsNone(build_robots_policy('', 404)['crawlDelaySec'])


class CrawlDelayCapture(unittest.TestCase):
    def test_requests_are_serial_and_spaced(self):
        class Handler(Site):
            robots = 'User-agent: *\nCrawl-delay: 1\nAllow: /\n'
            rate_limited = {}
        graph, hits = capture(Handler, '--render', 'never')
        site_hits = [hit for hit in hits if hit[1] not in ('/robots.txt',)]
        times = [t for t, _path, _ua in site_hits]
        self.assertGreaterEqual(len(times), 5, site_hits)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(gap >= 0.9 for gap in gaps), f'requests closer than the Crawl-delay: {gaps}')
        self.assertTrue(any('Crawl' in w or 'between requests' in w for w in graph.get('captureWarnings', [])), graph.get('captureWarnings'))
        self.assertTrue(all(ua == DEFAULT_USER_AGENT for _t, _p, ua in hits), {ua for _t, _p, ua in hits})


class RateLimitCapture(unittest.TestCase):
    def test_429_pauses_then_retries_once(self):
        class Handler(Site):
            rate_limited = {'/b': 1}
        graph, hits = capture(Handler, '--render', 'never')
        b_hits = [t for t, path, _ua in hits if path == '/b']
        self.assertEqual(len(b_hits), 2, 'retried exactly once')
        self.assertGreaterEqual(b_hits[1] - b_hits[0], 0.9, 'waited for Retry-After')
        node = next(n for n in graph['nodes'] if n.get('url', '').endswith('/b'))
        self.assertEqual(node.get('statusCode'), 200)

    def test_503_with_retry_after_pauses(self):
        class Handler(Site):
            limit_status = 503
            rate_limited = {'/b': 1}
        _graph, hits = capture(Handler, '--render', 'never')
        b_hits = [t for t, path, _ua in hits if path == '/b']
        self.assertEqual(len(b_hits), 2)
        self.assertGreaterEqual(b_hits[1] - b_hits[0], 0.9)

    def test_bare_503_is_retried_once_without_stopping_the_crawl(self):
        class Handler(Site):
            limit_status = 503
            retry_after = ''
            pages = ('/a', '/b', '/c', '/d')
            rate_limited = {'/a': -1, '/b': -1, '/c': -1}
        graph, hits = capture(Handler, '--render', 'never')
        for path in ('/a', '/b', '/c'):
            self.assertEqual(sum(1 for _t, p, _ua in hits if p == path), 2, path)
        self.assertIn('/d', [p for _t, p, _ua in hits], 'three broken pages do not halt the crawl')
        self.assertFalse(any('stopped requesting new pages' in w for w in graph.get('captureWarnings', [])))

    def test_repeated_429_stops_requesting_pages(self):
        class Handler(Site):
            pages = tuple(f'/p{i}' for i in range(8))
            rate_limited = {f'/p{i}': -1 for i in range(8)}
        graph, hits = capture(Handler, '--render', 'never')
        page_hits = [path for _t, path, _ua in hits if path.startswith('/p')]
        self.assertLess(len(page_hits), 8, f'kept requesting after being rate limited: {page_hits}')
        self.assertTrue(any('stopped requesting new pages' in w for w in graph.get('captureWarnings', [])), graph.get('captureWarnings'))


class BrowserIdentityCapture(unittest.TestCase):
    def test_rendered_pages_send_the_same_user_agent(self):
        class Handler(Site):
            pages = ('/a',)
            rate_limited = {}
        try:
            _graph, hits = capture(Handler, '--render', 'always')
        except RuntimeError as exc:
            if re.search(r'chromium|playwright|browser', str(exc), re.I):
                self.skipTest(f'No browser available: {exc}')
            raise
        agents = {ua for _t, path, ua in hits if path in ('/', '/a')}
        self.assertEqual(agents, {DEFAULT_USER_AGENT}, agents)


if __name__ == '__main__':
    unittest.main(verbosity=2)
