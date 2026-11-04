#!/usr/bin/env python3
"""Page notes mirror the page: landmarks kept and labelled, readable resource and link
sections, a property table instead of a pipe line, and full-page snapshots on top.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))

from markdown_converter import convert_html_to_markdown  # noqa: E402

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082')

PAGE = '''<!doctype html><html lang="en"><head><title>{title} | Fixture</title>
<meta name="description" content="{title} page of the note structure fixture.">
<link rel="preload" href="/fonts/brand-sans.woff2" as="font" type="font/woff2" crossorigin>
<style>.tall{{height:2600px;background:linear-gradient(#fff,#ccd)}}</style></head>
<body>
<a class="skip" href="#main">Skip to content</a>
<aside class="rail" aria-label="Page sections"><span>On this page</span></aside>
<header class="top">
  <a class="logo" href="/">Fixture Co</a>
  <nav aria-label="Main"><a href="/">Home</a> <a href="/about/">About us</a> <a href="/pricing/">Pricing</a></nav>
  <div class="right"><a class="btn" href="/contact/">Book a call</a><div role="group"><button>Light</button><button>Dark</button></div><button>Menu</button></div>
</header>
<main id="main">
  <p class="eyebrow">Guide</p>
  <h1>{title}</h1>
  <p>Intro paragraph with an <a href="https://partner.example/tools">external partner tool</a> and some words.</p>
  <div class="ctas"><a class="btn" href="/contact/">Talk to us</a><a href="/pricing/">See pricing</a></div>
  <h2>Section two</h2>
  <ul><li>First point</li><li>Second point with <strong>bold</strong></li></ul>
  <img src="/team.png" alt="The fixture team at work" width="1" height="1">
  <blockquote><p>A quote that must stay a quote.</p></blockquote>
  <table><thead><tr><th>Plan</th><th>Price</th></tr></thead><tbody><tr><td>Basic</td><td>10</td></tr></tbody></table>
  <h3>Deeper heading</h3>
  <p>{body}</p>
  <div class="tall"></div>
</main>
<footer>
  <div class="cols"><div><span class="cap">Person</span>Jane Fixture</div><div><span class="cap">Location</span><a href="/about/">Raleigh, NC</a></div></div>
  <nav aria-label="Footer"><a href="/privacy/">Privacy</a> <a href="/about/">About us</a></nav>
  <a href="#top">Back to top</a>
</footer>
</body></html>'''

PAGES = {'/': 'Home', '/about/': 'About', '/pricing/': 'Pricing', '/contact/': 'Contact', '/privacy/': 'Privacy'}


def page_html(path):
    return PAGE.format(title=PAGES[path], body=' '.join(['word'] * 150)).encode()


class Site(BaseHTTPRequestHandler):
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
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if path == '/robots.txt':
            return self.send(200, f'User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n'.encode(), 'text/plain')
        if path == '/sitemap.xml':
            urls = ''.join(f'<url><loc>{origin}{p}</loc></url>' for p in PAGES)
            return self.send(200, f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'.encode(), 'application/xml')
        if path == '/team.png':
            return self.send(200, PNG, 'image/png')
        if path == '/fonts/brand-sans.woff2':
            return self.send(200, b'wOF2' + b'\0' * 60, 'font/woff2')
        if path in PAGES:
            return self.send(200, page_html(path))
        if path + '/' in PAGES:
            return self.send(301, location=path + '/')
        self.send(404, b'Not found', 'text/plain')


def capture(*extra):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port
    temp = tempfile.TemporaryDirectory()
    vault = Path(temp.name)
    (vault / '.obsidian').mkdir()
    env = {**os.environ, 'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{port}'}
    try:
        completed = subprocess.run(
            [sys.executable, str(ROOT / 'engine' / 'crawl_site.py'), f'http://127.0.0.1:{port}', '--vault', str(vault),
             '--max-pages', '10', '--no-check-external', '--delay', '0', '--no-browser-audit', '--no-dns-checks', *extra],
            env=env, capture_output=True, text=True, encoding='utf-8', timeout=300)
    finally:
        server.shutdown()
    if completed.returncode != 0:
        errors = [line for line in completed.stdout.splitlines() if '"event": "error"' in line]
        temp.cleanup()
        raise RuntimeError((completed.stderr or '\n'.join(errors) or completed.stdout)[-2000:])
    return temp, vault / 'sites' / f'127.0.0.1-{port}'


def jpeg_size(data: bytes):
    """Width and height from the first JPEG start-of-frame marker."""
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack('>HH', data[i + 5:i + 9])
            return width, height
        i += 2 + length
    return None


class ConverterRegions(unittest.TestCase):
    def setUp(self):
        self.regions = []
        self.md = convert_html_to_markdown(page_html('/about/').decode(), 'https://fixture.example/about/', regions_out=self.regions)

    def test_skip_and_back_to_top_links_are_not_content(self):
        everything = self.md + '\n'.join(r['markdown'] for r in self.regions)
        self.assertNotIn('Skip to content', everything)
        self.assertNotIn('Back to top', everything)

    def test_landmarks_are_kept_labelled_and_ordered(self):
        labels = [(r['label'], r['position']) for r in self.regions]
        self.assertIn(('Sidebar: Page sections', 'before'), labels)
        self.assertIn(('Header', 'before'), labels)
        self.assertIn(('Footer', 'after'), labels)
        header = next(r for r in self.regions if r['kind'] == 'header')['markdown']
        self.assertIn('[About us](https://fixture.example/about/)', header)
        self.assertIn('[Book a call](https://fixture.example/contact/)', header)
        for noise in ('Light', 'Dark', 'Menu'):
            self.assertNotIn(noise, header, 'theme and menu toggles are controls, not content')
        footer = next(r for r in self.regions if r['kind'] == 'footer')['markdown']
        self.assertIn('Person Jane Fixture', footer, 'label and value stay apart')
        self.assertIn('[Raleigh, NC](https://fixture.example/about/)', footer, 'links inside label rows survive')
        self.assertNotIn('Home', self.md.split('# About')[0].replace('Guide', ''), 'navigation is not in the main content')

    def test_main_content_keeps_its_structure(self):
        self.assertIn('# About', self.md)
        self.assertIn('## Section two', self.md)
        self.assertIn('### Deeper heading', self.md)
        self.assertIn('- First point', self.md)
        self.assertIn('**bold**', self.md)
        self.assertIn('![The fixture team at work](https://fixture.example/team.png)', self.md)
        self.assertIn('> A quote that must stay a quote.', self.md)
        self.assertIn('| Plan | Price |', self.md)
        self.assertIn('[Talk to us](https://fixture.example/contact/)', self.md)
        self.assertIn('[See pricing](https://fixture.example/pricing/)', self.md, 'a row of buttons stays a row of links')
        self.assertNotIn('**Talk to us**:', self.md)


class CapturedNotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp, cls.site = capture('--render', 'never')
        cls.note = (cls.site / 'pages' / 'about.md').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_property_table_replaces_the_pipe_line(self):
        self.assertIn('| Property | Value |', self.note)
        self.assertRegex(self.note, r'\| Status \| 200 · \d+ ms \|')
        self.assertNotIn('**Health:**', self.note)
        self.assertNotIn('| Health | Redirects |', self.note, 'a page fetched at its published address is not a redirect')

    def test_regions_render_as_collapsed_callouts_around_the_content(self):
        content = self.note.split('## Page Content', 1)[1].split('\n## Media and Resources', 1)[0]
        self.assertIn('> [!info]- Header', content)
        self.assertIn('> [!info]- Footer', content)
        self.assertLess(content.index('> [!info]- Header'), content.index('# About'))
        self.assertGreater(content.index('> [!info]- Footer'), content.index('# About'))
        self.assertNotIn('Skip to content', content)

    def test_media_section_uses_real_labels_grouped_by_type(self):
        media = self.note.split('## Media and Resources', 1)[1].split('\n## ', 1)[0]
        self.assertIn('**Images**', media)
        self.assertIn('The fixture team at work', media)
        self.assertIn('**Fonts**', media)
        self.assertIn('brand-sans.woff2', media)
        self.assertNotRegex(media, r'- (image|font|script): ')
        self.assertNotIn('(ok)', media)

    def test_external_links_are_one_bullet_with_anchor_text(self):
        section = self.note.split('## Outgoing External Links', 1)[1].split('\n## ', 1)[0]
        self.assertIn('[external partner tool](https://partner.example/tools)', section)
        self.assertNotRegex(section, r'https?://\S+, https?://')

    def test_site_chrome_links_are_grouped_markdown_links(self):
        section = self.note.split('## Navigation & Footer Links (Site Chrome)', 1)[1].split('\n## ', 1)[0]
        self.assertIn('**Header**', section)
        self.assertRegex(section, r'- \[Fixture Co\]\(http://127\.0\.0\.1:\d+/\)')
        self.assertIn('**Footer**', section)
        self.assertRegex(section, r'- \[Privacy\]\(http://127\.0\.0\.1:\d+/privacy/\)')
        self.assertNotIn('/pricing/', section, 'a page also linked from the body is listed as a contextual link instead')
        self.assertNotIn('`', section)


class Snapshots(unittest.TestCase):
    def test_full_page_snapshot_is_saved_and_embedded_on_top(self):
        try:
            temp, site = capture('--render', 'auto', '--snapshot-limit', '2', '--snapshot-html')
        except RuntimeError as exc:
            if re.search(r'chromium|playwright|browser', str(exc), re.I):
                self.skipTest(f'No browser available: {exc}')
            raise
        try:
            shots = sorted((site / 'assets' / 'screenshots').glob('full-*.jpg'))
            if not shots:
                graph = json.loads((site / '_site-graph.json').read_text(encoding='utf-8'))
                detail = ((graph.get('siteIntel') or {}).get('snapshots') or {}).get('detail', '')
                if re.search(r'chromium|playwright|browser', detail, re.I):
                    self.skipTest(detail)
                self.fail(f'no snapshots saved: {detail}')
            self.assertEqual(len(shots), 2, 'the limit is respected')
            size = jpeg_size(shots[0].read_bytes())
            self.assertIsNotNone(size)
            self.assertEqual(size[0], 1280)
            self.assertGreater(size[1], 2000, 'the whole page, not just the first screen')
            self.assertEqual(len(list((site / 'assets' / 'snapshots').glob('full-*.html'))), 2)
            home = (site / 'pages' / 'index.md').read_text(encoding='utf-8') if (site / 'pages' / 'index.md').exists() else ''
            notes = [p.read_text(encoding='utf-8') for p in (site / 'pages').rglob('*.md')]
            with_snapshot = [n for n in notes if '> [!example]- Page snapshot' in n]
            self.assertEqual(len(with_snapshot), 2)
            for note in with_snapshot:
                body = note.split('\n---\n', 1)[1]
                title_line = next(i for i, line in enumerate(body.splitlines()) if line.startswith('# '))
                callout_line = next(i for i, line in enumerate(body.splitlines()) if 'Page snapshot' in line)
                self.assertEqual(callout_line, title_line + 2, 'right under the title')
                self.assertRegex(note, r'!\[\[sites/127\.0\.0\.1-\d+/assets/screenshots/full-[a-z0-9-]+\.jpg\|Full-page snapshot\]\]')
                self.assertIn('rendered HTML]]', note)
            self.assertTrue(home == '' or '> [!example]- Page snapshot' in home, 'home is snapshotted first')
            graph = json.loads((site / '_site-graph.json').read_text(encoding='utf-8'))
            self.assertEqual(sum(1 for n in graph['nodes'] if n.get('snapshot')), 2)
        finally:
            temp.cleanup()

    def test_no_snapshots_flag_saves_none(self):
        temp, site = capture('--render', 'never', '--no-snapshots')
        try:
            self.assertEqual(list((site / 'assets' / 'screenshots').glob('full-*.jpg')) if (site / 'assets' / 'screenshots').exists() else [], [])
            notes = ''.join(p.read_text(encoding='utf-8') for p in (site / 'pages').rglob('*.md'))
            self.assertNotIn('Page snapshot', notes)
        finally:
            temp.cleanup()


if __name__ == '__main__':
    unittest.main(verbosity=2)
