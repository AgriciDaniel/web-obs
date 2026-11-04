#!/usr/bin/env python3
"""Integrated capture coverage tests with two local HTTP origins only."""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import requests
import crawl_site
import extractor
import markdown_converter


class External(BaseHTTPRequestHandler):
    hits = []
    def log_message(self, *_args):
        pass
    def do_HEAD(self):
        self.hits.append(self.path)
        code = {'/ok': 200, '/gone': 404, '/denied': 403, '/server-error': 503}.get(self.path, 404)
        self.send_response(code)
        self.end_headers()

    def do_GET(self):
        # Missing destinations must confirm the same status when checked by GET.
        self.do_HEAD()


class Website(BaseHTTPRequestHandler):
    mode = 'basic'
    version = 1
    external_port = 0
    hits = []
    def log_message(self, *_args):
        pass
    def do_GET(self):
        self.hits.append(self.path)
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if self.path == '/robots.txt':
            if self.mode == 'unavailable':
                self.send_response(503)
                self.end_headers()
                return
            content = f'User-agent: *\nAllow: /\nUser-agent: WebObs\nDisallow: /private\nSitemap: {origin}/sitemap.xml'
            kind = 'text/plain'
        elif self.path == '/sitemap.xml':
            paths = ['/', '/private'] + ([f'/page-{i}' for i in range(60)] if self.mode == 'graph' else [])
            content = '<urlset>' + ''.join(f'<url><loc>{origin}{p}</loc></url>' for p in paths) + '</urlset>'
            kind = 'application/xml'
        elif self.path == '/' or self.path.startswith('/page-'):
            text = 'Alpha source sentence.' if self.version == 1 else 'Bravo source sentence.'
            links = ''.join(f'<a href="http://localhost:{self.external_port}{path}">{path}</a>' for path in ['/ok', '/gone', '/denied', '/server-error'])
            if self.mode == 'graph':
                links += ''.join(f'<a href="https://d{i}.example/resource">Reference {i}</a>' for i in range(70))
            content = f'<html><head><title>Source business</title><meta name="description" content="Source description"></head><body><section><h1>Important hero</h1></section><main><p>{text} ' + ('Verifiable public text. ' * 30) + '</p>' + links + '<button aria-controls="answer">A question?</button><div hidden id="answer">Hidden FAQ answer.</div></main></body></html>'
            kind = 'text/html'
        elif self.path == '/redirect-private':
            self.send_response(302)
            self.send_header('Location', '/private')
            self.end_headers()
            return
        elif self.path == '/private':
            content, kind = '<h1>Should never be requested</h1>', 'text/html'
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.end_headers()
        self.wfile.write(content.encode())


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.external = ThreadingHTTPServer(('127.0.0.1', 0), External)
        cls.website = ThreadingHTTPServer(('127.0.0.1', 0), Website)
        Website.external_port = cls.external.server_port
        cls.threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (cls.external, cls.website)]
        for thread in cls.threads:
            thread.start()
        cls.origin = f'http://127.0.0.1:{cls.website.server_port}'
        cls.env = patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{cls.website.server_port},localhost:{cls.external.server_port}'})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.external, cls.website):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(2)
        cls.env.stop()

    def setUp(self):
        Website.mode, Website.version = 'basic', 1
        Website.hits.clear()
        External.hits.clear()
        self.unexpected = []
        original = requests.Session.request
        permitted = {('127.0.0.1', self.website.server_port), ('localhost', self.external.server_port)}
        def guarded(session, method, url, *args, **kwargs):
            parsed = urlparse(url)
            if (parsed.hostname, parsed.port) not in permitted or method.upper() not in ('GET', 'HEAD'):
                self.unexpected.append(url)
                raise AssertionError('Unexpected outbound request: ' + url)
            return original(session, method, url, *args, **kwargs)
        self.guard = patch.object(requests.Session, 'request', guarded)
        self.guard.start()

    def tearDown(self):
        self.guard.stop()
        self.assertEqual(self.unexpected, [])

    def capture(self, directory, **kwargs):
        with redirect_stdout(io.StringIO()):
            return crawl_site.crawl_website_to_vault(self.origin, directory, render_mode='never', delay_sec=0, download_images=False, **kwargs)

    def test_capture_connects_link_checks_robots_receipts_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            self.assertNotIn('/private', Website.hits)
            self.assertEqual(set(External.hits), {'/ok', '/gone', '/denied', '/server-error'})
            self.assertEqual(manifest['linkHealth']['totalCount'], 4)
            self.assertEqual(len(manifest['linkHealth']['brokenLinks']), 1)
            self.assertEqual(len(manifest['linkHealth']['serverErrors']), 1)
            self.assertEqual(manifest['linkHealth']['unknownCount'], 1)
            site = Path(directory) / 'sites' / manifest['siteId']
            for name in ('_fetch-log.json', '_fetch-log.md', '_evidence-pack.md', '_link-health.json', '_pages.base', '_generated-files.json'):
                self.assertTrue((site / name).is_file(), name)
            receipts = json.loads((site / '_fetch-log.json').read_text(encoding='utf-8'))
            row = next(row for row in receipts['entries'] if row.get('rawPath'))
            self.assertEqual(hashlib.sha256((site / row['rawPath']).read_bytes()).hexdigest(), row['rawSha256'])
            note = (site / 'pages/index.md').read_text(encoding='utf-8')
            for token in ('Important hero', 'Hidden FAQ answer.', 'authority_score:', 'kind:', 'path:'):
                self.assertIn(token, note)
            self.assertEqual(len(json.loads((site / '_pages.base').read_text(encoding='utf-8'))['views']), 9)
            self.assertIn('FETCH', (site / '_evidence-pack.md').read_text(encoding='utf-8'))

    def test_unknown_robots_does_not_request_pages(self):
        Website.mode = 'unavailable'
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            self.assertEqual(manifest['stats']['pagesCrawled'], 0)
            self.assertEqual(manifest['captureStatus'], 'partial')
            self.assertNotIn('/', Website.hits)
            self.assertNotIn('pagesWithSeoIssues', manifest['stats'])

    def test_all_observed_domains_and_sources_are_stored(self):
        Website.mode = 'graph'
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory, check_external=False)
            self.assertEqual(manifest['stats']['pagesCrawled'], 61)
            domains = [n for n in manifest['nodes'] if n['kind'] == 'external-domain']
            self.assertEqual(len(domains), 71)
            self.assertEqual(manifest['stats']['externalDomains'], 71)
            edges = [e for e in manifest['edges'] if e['kind'] == 'external' and e.get('targetUrl', '').endswith('/ok')]
            self.assertEqual(len(edges), 61)
            self.assertEqual(len(list((Path(directory) / 'sites' / manifest['siteId'] / '_external').glob('*.md'))), 71)

    def test_content_drift_is_written_on_equal_word_count_change(self):
        with tempfile.TemporaryDirectory() as directory:
            self.capture(directory, check_external=False)
            Website.version = 2
            manifest = self.capture(directory, check_external=False)
            self.assertTrue(manifest['drift']['hasChanges'])
            self.assertGreater(manifest['drift']['contentChangesCount'], 0)
            self.assertTrue((Path(directory) / 'sites' / manifest['siteId'] / '_drift-report.md').is_file())

    def test_http_redirect_respects_policy_before_following(self):
        result = extractor.fetch_page_html(self.origin + '/redirect-private', render_mode='never', allow_url=lambda url: not url.endswith('/private'))
        self.assertTrue(result['error'])
        self.assertNotIn('/private', Website.hits)

    def test_extraction_preserves_hero_controlled_faq_and_zero_price(self):
        html = '<section><h1>Hero</h1></section><main><p>' + 'Long detail. ' * 100 + '</p><button aria-controls="a">Question</button><div id="a" aria-hidden="true" style="display:none">Answer</div></main>'
        markdown = markdown_converter.convert_html_to_markdown(html, self.origin)
        self.assertIn('Hero', markdown)
        self.assertIn('Answer', markdown)
        entities = extractor._distill_schema_entities([{'@type': 'Product', 'name': 'Free', 'offers': {'price': 0}}], self.origin)
        self.assertEqual(entities['offersAndProducts'][0]['price'], '0')

    def test_svg_media_does_not_keep_executable_or_remote_references(self):
        raw = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><title>Chart</title><script>bad()</script><image href="https://outside.example/api"/><rect width="20" style="fill:url(https://outside.example/paint)"/><text>123</text></svg>'
        safe = extractor.sanitize_svg_bytes(raw)
        for token in (b'onload', b'<script', b'https://outside.example'):
            self.assertNotIn(token, safe)
        self.assertIn(b'123', safe)
        with self.assertRaises(ValueError):
            extractor.sanitize_svg_bytes(b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>')


if __name__ == '__main__':
    unittest.main(verbosity=2)
