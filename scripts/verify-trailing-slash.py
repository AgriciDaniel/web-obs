#!/usr/bin/env python3
"""A trailing-slash site must not report false redirects, and real ones must still show.

The fixture mimics WordPress permalinks: every page is published with a trailing
slash, the slashless form 301s to it, the sitemap and internal links use the
published form, one page really moves (/old/ to /new/), one internal link is
written without the slash, and one page is missing from the sitemap.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['/about/', '/blog/', '/blog/post-one/', '/new/', '/contact/', '/hidden/']
SITEMAPPED = ['/', '/about/', '/blog/', '/blog/post-one/', '/old/', '/new/', '/contact/']
requested = []


def page_html(title, links, content_images=''):
    anchors = ''.join(f'<a href="{href}">{label}</a> ' for href, label in links)
    return (f'<!doctype html><html lang="en"><head><title>{title} | Fixture</title>'
            f'<meta name="description" content="{title} description for the trailing slash fixture site.">'
            f'<meta name="viewport" content="width=device-width"></head>'
            f'<body><header><div aria-hidden="true"><a href="/"><img src="/logo.png" alt=""></a></div></header>'
            f'<main><h1>{title}</h1><h2>Overview</h2><p>{" ".join(["word"] * 120)}</p>{anchors}{content_images}</main>'
            f'<footer><h2>Footer</h2><h4>Footer widget</h4></footer></body></html>')


PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082')


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, status, body=b'', content_type='text/html; charset=utf-8', location=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if location:
            self.send_header('Location', location)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        requested.append(path)
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if path == '/robots.txt':
            return self.send(200, f'User-agent: *\nAllow: /\nSitemap: {origin}/sitemap_index.xml\n'.encode(), 'text/plain')
        if path in ('/sitemap.xml', '/sitemap-index.xml'):
            return self.send(301, location='/sitemap_index.xml')
        if path in ('/logo.png', '/content.png', '/decor.png'):
            return self.send(200, PNG, 'image/png')
        if path == '/sitemap_index.xml':
            urls = ''.join(f'<url><loc>{origin}{p}</loc></url>' for p in SITEMAPPED)
            return self.send(200, f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'.encode(), 'application/xml')
        if path == '/':
            links = [('/about/', 'About'), ('/blog/', 'Blog'), ('/old/', 'Old page'), ('/contact', 'Contact'), ('/hidden/', 'Hidden'), ('/new/', 'New')]
            images = '<img src="/content.png"><img src="/decor.png" alt=""><img src="/missing.png" alt="Missing">'
            return self.send(200, page_html('Home', links, images).encode())
        if path == '/old/':
            return self.send(301, location='/new/')
        if path in PAGES:
            links = [('/', 'Home'), ('/about/', 'About'), ('/blog/', 'Blog'), ('/blog/post-one/', 'Post'), ('/contact/', 'Contact')]
            return self.send(200, page_html(path.strip('/').replace('/', ' ').title(), links).encode())
        if path + '/' in PAGES or path + '/' == '/old/':
            time.sleep(.25)  # the slashless form is slow, like a cache miss followed by a redirect
            return self.send(301, location=path + '/')
        self.send(404, b'Not found', 'text/plain')


class TrailingSlashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        requested.clear()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port
        cls.origin = f'http://127.0.0.1:{cls.port}'
        cls.temp = tempfile.TemporaryDirectory()
        vault = Path(cls.temp.name)
        (vault / '.obsidian').mkdir()
        env = {**os.environ, 'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{cls.port}'}
        completed = subprocess.run(
            [sys.executable, str(ROOT / 'engine' / 'crawl_site.py'), cls.origin, '--vault', str(vault),
             '--max-pages', '30', '--no-check-external', '--render', 'never', '--delay', '0'],
            env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
        if completed.returncode != 0:
            errors = [line for line in completed.stdout.splitlines() if '"event": "error"' in line]
            raise RuntimeError((completed.stderr or '\n'.join(errors) or completed.stdout)[-2000:])
        site = vault / 'sites' / f'127.0.0.1-{cls.port}'
        cls.graph = json.loads((site / '_site-graph.json').read_text(encoding='utf-8'))
        cls.nodes = {urlsplit_path(node['url']): node for node in cls.graph['nodes'] if node.get('url')}
        cls.notes = '\n'.join(p.read_text(encoding='utf-8') for p in site.rglob('*.md'))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.temp.cleanup()

    def test_published_urls_are_fetched_exactly_as_published(self):
        for path in ('/about/', '/blog/', '/blog/post-one/', '/contact/'):
            self.assertIn(path, requested, f'{path} was never requested')
        for path in ('/about', '/blog', '/blog/post-one'):
            self.assertNotIn(path, requested, f'{path} was requested without the published trailing slash')

    def test_published_pages_report_no_redirect(self):
        for path in ('/about/', '/blog/', '/blog/post-one/', '/new/'):
            node = self.nodes[path]
            self.assertNotEqual(node['health'], 'redirect', path)
            self.assertNotIn('redirected-source-url', node.get('seoIssues') or node.get('issues') or [], path)

    def test_notes_record_the_published_address(self):
        self.assertIn(f'{self.origin}/about/', self.notes)
        self.assertNotIn(f'{self.origin}/about\n', self.notes)

    def test_real_redirect_is_still_reported(self):
        redirects = [urlsplit_path(url) for url in self.hygiene()['redirect']]
        self.assertIn('/old/', redirects)

    def test_slashless_link_names_the_published_address(self):
        mismatches = [m for node in self.graph['nodes'] for m in node.get('linkFormMismatches', [])]
        self.assertTrue(any(urlsplit_path(m['linked']) == '/contact' and urlsplit_path(m['published']) == '/contact/' for m in mismatches), mismatches)

    def test_sitemap_hygiene_counts_only_the_real_redirect(self):
        hygiene = self.hygiene()
        self.assertEqual([urlsplit_path(url) for url in hygiene['redirect']], ['/old/'])

    def test_unlisted_page_is_counted(self):
        self.assertEqual(self.graph['stats']['unlistedPages'], 1)
        self.assertIn('unlisted', self.nodes['/hidden/']['flags'])

    def test_a_page_can_carry_several_statuses(self):
        # /hidden/ is absent from the sitemap and linked from the home page only.
        self.assertEqual(self.nodes['/hidden/']['flags'], ['unlisted'])

    def test_slashless_internal_link_is_reported(self):
        issues = []
        for node in self.graph['nodes']:
            issues += node.get('seoIssues') or node.get('issues') or []
        self.assertTrue(any(str(issue).startswith('internal-link-form-mismatch') for issue in issues), issues)


    def test_sitemap_reached_through_aliases_is_counted_once(self):
        self.assertEqual(self.graph['stats']['sitemapsFound'], 1)
        self.assertEqual(len(self.graph['sitemaps']), 1)
        self.assertEqual(self.hygiene()['undeclaredSitemaps'], [])

    def test_alt_text_rules(self):
        home = self.nodes['/']
        # The logo sits in an aria-hidden container, so it is decorative. One content image has
        # no alt attribute at all, and one content image has an empty alt.
        self.assertEqual(home['imagesMissingAlt'], 1)
        self.assertEqual(home['imagesEmptyAlt'], 1)
        issues = self.issues('/')
        self.assertTrue(any(issue.startswith('images-missing-alt (1)') for issue in issues), issues)

    def test_footer_heading_jump_is_not_a_content_skip(self):
        issues = self.issues('/about/')
        self.assertNotIn('heading-level-skip', issues)
        self.assertEqual(self.nodes['/about/']['templateHeadingSkips'], 1)

    def test_broken_resource_is_a_finding_not_a_partial_capture(self):
        self.assertTrue(any('/missing.png' in finding for finding in self.graph['captureFindings']), self.graph['captureFindings'])
        self.assertEqual(self.graph['captureStatus'], 'complete', self.graph['captureWarnings'])

    def test_response_time_excludes_redirect_hops(self):
        from urllib.parse import urlsplit
        sys.path.insert(0, str(ROOT / 'engine'))
        os.environ['WEB_OBS_LOCAL_TARGETS'] = f'127.0.0.1:{self.port}'
        from page_fetch import PageFetcher
        fetcher = PageFetcher()
        try:
            result = fetcher.fetch(self.origin + '/contact', render_mode='never')
        finally:
            fetcher.close()
        self.assertEqual(result['redirect_hops'], 1)
        self.assertGreaterEqual(result['fetch_duration_ms'], 240)
        self.assertLess(result['response_time_ms'], result['fetch_duration_ms'] - 200)
        self.assertLessEqual(result['ttfb_ms'], result['response_time_ms'])

    def issues(self, path):
        for node in self.graph['nodes']:
            if node.get('url') and urlsplit_path(node['url']) == path:
                return node.get('seoIssues') or node.get('issues') or []
        return []

    def hygiene(self):
        intel = self.graph.get('siteIntel') or self.graph.get('stackIntel') or {}
        for holder in (self.graph, intel, intel.get('aiReadiness') or {}):
            if isinstance(holder, dict) and 'sitemapHygiene' in holder:
                return holder['sitemapHygiene']
        return self.find_key(self.graph, 'sitemapHygiene')

    @staticmethod
    def find_key(value, key):
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for child in value.values():
                found = TrailingSlashTests.find_key(child, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = TrailingSlashTests.find_key(child, key)
                if found is not None:
                    return found
        return None


def urlsplit_path(url):
    from urllib.parse import urlsplit
    return urlsplit(url).path or '/'


if __name__ == '__main__':
    unittest.main(verbosity=2)
