#!/usr/bin/env python3
"""Verify media classification, source associations, and bounded local asset writes."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
import extractor
import resources
from bs4 import BeautifulSoup


class Fixture(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.hits.append(self.path)
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/image')
            self.end_headers()
            return
        status, kind, body = {
            '/audio': (200, 'text/html', b'<html><h1>Audio landing page</h1></html>'),
            '/stream': (200, 'audio/aac', b'fixture audio bytes'),
            '/captions': (200, 'text/vtt', b'WEBVTT\n\n00:00.000 --> 00:01.000\nHello'),
            '/image': (200, 'image/png', b'fixture image bytes'),
            '/wrong.png': (200, 'text/html', b'<html>Not image bytes</html>'),
            '/attachment': (200, 'application/octet-stream', b'fixture document'),
            '/oversize': (200, 'image/png', b'x' * 1024),
            '/empty': (200, 'image/png', b''),
            '/denied': (403, 'text/plain', b'Forbidden'),
            '/missing': (404, 'text/plain', b'Not found'),
        }.get(self.path, (404, 'text/plain', b'Not found'))
        self.send_response(status)
        self.send_header('Content-Type', kind)
        if self.path == '/attachment':
            self.send_header('Content-Disposition', 'attachment; filename="guide.pdf"')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.env = patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{cls.server.server_port}'})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        Fixture.hits.clear()
        request = requests.Session.request
        origin = self.origin
        def local_only(session, method, url, *args, **kwargs):
            self.assertEqual(urlparse(url).netloc, urlparse(origin).netloc, 'Unexpected network destination')
            return request(session, method, url, *args, **kwargs)
        self.guard = patch.object(requests.Session, 'request', local_only)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_non_page_url_hints_and_html_landing_pages(self):
        for suffix, kind in [('.vtt', 'transcript'), ('.srt', 'transcript'), ('.m4a', 'audio'),
                             ('.aac', 'audio'), ('.m3u8', 'video'), ('.mpd', 'video'), ('.pdf', 'document')]:
            with self.subTest(suffix=suffix):
                url = f'https://fixture.example/media{suffix}?v=3'
                self.assertEqual(resources.classify_resource(url)['type'], kind)
                self.assertFalse(extractor.is_crawlable_page_url(url))
        for path in ['/audio', '/watch', '/video-tools']:
            self.assertTrue(extractor.is_crawlable_page_url(self.origin + path))
            self.assertEqual(resources.classify_resource(self.origin + path, 'text/html; charset=utf-8')['type'], 'page')
        self.assertEqual(resources.classify_resource(self.origin + '/wrong.png', 'text/html')['type'], 'page')

    def test_download_attribute_keeps_specific_caption_type(self):
        from bs4 import BeautifulSoup
        from resources import extract_resource_references
        rows = extract_resource_references(BeautifulSoup('<a download href="/captions.vtt">Download English captions</a>', 'html.parser'), 'https://example.test/article')
        self.assertEqual(rows[0]['type'], 'transcript')
        self.assertEqual(rows[0]['label'], 'Download English captions')
        self.assertEqual(resources.classify_resource('https://example.test/captions.vtt', declared_type='document')['type'], 'transcript')

    def test_authoritative_headers_and_attachments(self):
        self.assertEqual(resources.classify_resource(self.origin + '/stream', 'audio/aac')['type'], 'audio')
        self.assertEqual(resources.classify_resource(self.origin + '/captions', 'text/vtt')['type'], 'transcript')
        self.assertEqual(resources.classify_resource(self.origin + '/captions.vtt', 'text/plain')['type'], 'transcript')
        self.assertEqual(resources.classify_resource(self.origin + '/asset', 'application/octet-stream',
                         'attachment; filename="captions.srt"')['type'], 'transcript')
        self.assertEqual(resources.classify_resource(self.origin + '/asset', 'audio/aac',
                         'attachment')['type'], 'audio')
        self.assertEqual(resources.classify_resource(self.origin + '/asset', 'text/html',
                         'attachment; filename="copy.html"')['type'], 'document')

    def test_image_srcset_does_not_fabricate_data_url_paths(self):
        soup = BeautifulSoup('<picture><source srcset="data:image/png;base64,AAAA 1x, /retina.png 2x">'
                             '<img src="/small.png" srcset="/medium.png 1x, /large.png 2x"></picture>', 'html.parser')
        inventory = resources.extract_resource_references(soup, self.origin + '/')
        self.assertEqual({item['url'] for item in inventory},
                         {self.origin + path for path in ['/retina.png', '/small.png', '/medium.png', '/large.png']})
        data = extractor.extract_page_data('<html><title>Data image</title><h1>Embedded image</h1>'
                                          '<img srcset="data:image/png;base64,AAAA 1x"></html>',
                                          self.origin + '/', '127.0.0.1')
        self.assertEqual(data['images'], [])
        self.assertEqual(data['resources'], [])

    def test_inventory_preserves_tracks_posters_and_download_check_targets(self):
        html = '''<html lang="en"><head><title>Media fixtures</title>
          <link rel="stylesheet" href="/style.css"><script src="/app.js"></script></head><body>
          <h1>Media library</h1><audio src="/voice.m4a" aria-label="Interview">
          <source src="/stream" type="audio/aac"></audio>
          <video src="/movie.mp4" type="video/mp4" poster="/poster" title="Product tour">
          <source src="/live.m3u8" type="application/vnd.apple.mpegurl">
          <track src="/captions" kind="captions" label="English subtitles" srclang="en" type="text/vtt"></video>
          <iframe src="https://www.youtube-nocookie.com/embed/123" title="Interview video"></iframe>
          <a href="/transcript.vtt">Transcript</a><a href="/audio">Audio library</a>
          <a href="/guide.pdf">Internal guide</a><a href="/attachment" download>Download guide</a>
          <a href="https://external.example/guide.pdf">External guide</a></body></html>'''
        page = self.origin + '/library'
        data = extractor.extract_page_data(html, page, '127.0.0.1')
        items = {(entry['url'], entry['role']): entry for entry in data['resources']}
        self.assertEqual(items[(self.origin + '/stream', 'audio-source')]['type'], 'audio')
        self.assertEqual(items[(self.origin + '/stream', 'audio-source')]['label'], 'Interview')
        self.assertEqual(items[(self.origin + '/poster', 'poster')]['type'], 'image')
        caption = items[(self.origin + '/captions', 'captions')]
        self.assertEqual((caption['type'], caption['language'], caption['label'], caption['sourcePage']),
                         ('transcript', 'en', 'English subtitles', page))
        self.assertEqual(items[(self.origin + '/live.m3u8', 'video-source')]['type'], 'video')
        self.assertEqual(items[('https://www.youtube-nocookie.com/embed/123', 'embed')]['type'], 'video')
        internal = {entry['url'] for entry in data['internal_links']}
        self.assertIn(self.origin + '/audio', internal)
        self.assertNotIn(self.origin + '/transcript.vtt', internal)
        self.assertNotIn(self.origin + '/attachment', internal)
        self.assertIn('https://external.example/guide.pdf', {entry['url'] for entry in data['external_links']})
        self.assertEqual(len(data['downloads']), 3)

    def test_bounded_asset_fetch_and_status_evidence(self):
        result = resources.fetch_asset(self.origin + '/redirect')
        self.assertEqual((result['status_code'], result['resource_type']), (200, 'image'))
        self.assertEqual(result['sha256'], hashlib.sha256(result['raw_bytes']).hexdigest())
        self.assertEqual(result['final_url'], self.origin + '/image')
        self.assertEqual(len(result['redirect_chain']), 1)
        for path, expected in [('/denied', 403), ('/missing', 404)]:
            result = resources.fetch_asset(self.origin + path)
            self.assertEqual(result['status_code'], expected)
            self.assertEqual(result['error_kind'], 'http')
            self.assertEqual(result['raw_bytes'], b'')
        self.assertEqual(resources.fetch_asset(self.origin + '/oversize', max_bytes=100)['error_kind'], 'size-limit')
        self.assertEqual(resources.fetch_asset(self.origin + '/empty')['error_kind'], 'empty')
        self.assertEqual(resources.fetch_asset(self.origin + '/attachment')['resource_type'], 'document')

    def test_policy_checked_again_on_redirect(self):
        result = resources.fetch_asset(self.origin + '/redirect', allow_url=lambda url: not url.endswith('/image'))
        self.assertEqual(result['error_kind'], 'policy')
        self.assertEqual(Fixture.hits, ['/redirect'])

    def test_writer_rejects_html_and_shares_inline_svg_budget(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script><rect width="2" height="2" onload="bad()"/></svg>'
        with tempfile.TemporaryDirectory() as folder:
            writer = extractor.LocalAssetDownloader(folder, max_images_total=1)
            self.assertEqual(writer.save_inline_svg('inline:one', 'chart.svg', svg), 'chart.svg')
            saved = (Path(folder) / 'chart.svg').read_text(encoding='utf-8')
            self.assertNotIn('<script', saved)
            self.assertNotIn('onload', saved)
            self.assertIsNone(writer.save_inline_svg('inline:two', 'second.svg', svg))
            self.assertIsNone(writer.download_image(self.origin + '/image'))
            self.assertEqual(Fixture.hits, [])
            self.assertEqual(writer.total_bytes, (Path(folder) / 'chart.svg').stat().st_size)
            self.assertEqual(writer.downloaded_count, 1)
        with tempfile.TemporaryDirectory() as folder:
            result = resources.fetch_asset(self.origin + '/image')
            writer = extractor.LocalAssetDownloader(folder, max_total_bytes=len(result['raw_bytes']))
            self.assertIsNotNone(writer.save_download_result(self.origin + '/image', result))
            self.assertIsNone(writer.save_inline_svg('inline:one', 'chart.svg', svg))
            self.assertEqual(writer.total_bytes, len(result['raw_bytes']))
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
        with tempfile.TemporaryDirectory() as folder:
            writer = extractor.LocalAssetDownloader(folder)
            result = resources.fetch_asset(self.origin + '/wrong.png')
            self.assertIsNone(writer.save_download_result(self.origin + '/wrong.png', result))
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
