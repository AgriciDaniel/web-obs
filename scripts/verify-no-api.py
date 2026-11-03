#!/usr/bin/env python3
"""Local fixtures and network tripwires for the no external API contract."""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import requests
import brand_and_dns
import crawl_site
import extractor
import site_intel
from url_safety import make_safe_playwright_route_handler


class Fixture(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.hits.append(self.path)
        origin = f"http://127.0.0.1:{self.server.server_port}"
        status, content_type = 200, "text/html"
        if self.path == "/robots.txt":
            content_type = "text/plain"
            body = f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n"
        elif self.path == "/sitemap.xml":
            content_type = "application/xml"
            body = f'<urlset><url><loc>{origin}/</loc></url></urlset>'
        elif self.path == "/":
            body = '''<html lang="en"><head><title>Local business</title>
            <meta name="description" content="Fixture description">
            <link rel="alternate" type="text/markdown" href="/page.md">
            <script>var marker='G-TEST12345';</script></head><body><main>
            <h1>Public fixture website</h1><p>Locally observed content and contacts.</p>
            <a href="https://example.com/reference">An external link</a>
            <a href="mailto:hello@example.com">Contact us</a>
            </main></body></html>'''
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", type(self).redirect_target)
            self.end_headers()
            return
        elif self.path == "/render":
            body = f'''<html><head><title>Render fixture</title></head><body>
            <h1 id="result">Waiting</h1><script src="/static.js"></script>
            <script>
            fetch('/api/data').catch(()=>{{}});
            fetch('https://dns.google/resolve?name=example.com').catch(()=>{{}});
            fetch('/api/post',{{method:'POST',body:'test'}}).catch(()=>{{}});
            navigator.sendBeacon('/beacon','test');
            navigator.serviceWorker.register('/worker.js').catch(()=>{{}});
            try{{new WebSocket('ws://127.0.0.1:{self.server.server_port}/socket')}}catch(e){{}}
            </script></body></html>'''
        elif self.path == "/static.js":
            content_type = "application/javascript"
            body = "document.getElementById('result').textContent='Rendered locally';"
        else:
            status, content_type, body = 404, "text/plain", "Not found"
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        self.hits.append(self.path)
        self.send_response(200)
        self.end_headers()


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        from browser_runtime import resolve_chromium_executable
        with sync_playwright() as driver:
            return bool(resolve_chromium_executable(driver).get('executablePath'))
    except Exception:
        return False


NEEDS_BROWSER = unittest.skipUnless(chromium_available(), 'No compatible Chromium found, skipping browser rendering test.')


class NoApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.server.server_port}"})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.env.stop()

    def tripwire(self, seen):
        original = requests.Session.request

        def checked(session, method, url, *args, **kwargs):
            parsed = urlparse(url)
            self.assertEqual((parsed.hostname, parsed.port), ("127.0.0.1", self.server.server_port), f"Unexpected network destination: {url}")
            self.assertIn(method.upper(), ("GET", "HEAD"))
            self.assertFalse(session.trust_env, "A system proxy must not bypass destination checks")
            seen.append(url)
            return original(session, method, url, *args, **kwargs)

        return patch.object(requests.Session, "request", checked)

    def test_provider_integrations_are_absent(self):
        self.assertFalse(hasattr(site_intel, "lookup_domain_rdap"))
        self.assertFalse(hasattr(brand_and_dns, "lookup_passive_dns_and_tls"))
        self.assertFalse(hasattr(brand_and_dns, "probe_pagespeed_insights"))
        for source in (ROOT / "engine").glob("*.py"):
            text = source.read_text(encoding='utf-8')
            for endpoint in ("https://rdap.org", "https://dns.google/resolve", "https://crt.sh", "https://www.googleapis.com/pagespeedonline"):
                self.assertNotIn(endpoint, text, str(source))

    def test_http_capture_uses_only_direct_website_resources(self):
        seen = []
        with tempfile.TemporaryDirectory() as directory, self.tripwire(seen), redirect_stdout(io.StringIO()):
            vault = Path(directory)
            (vault / ".obsidian").mkdir()
            preferences = '{"colorGroups":[{"query":"tag:personal","color":{"a":1,"rgb":123}}],"lineSizeMultiplier":1.7}'
            (vault / ".obsidian" / "graph.json").write_text(preferences, encoding='utf-8')
            manifest = crawl_site.crawl_website_to_vault(self.origin, directory, max_pages=1, download_images=False, render_mode="never", delay_sec=0, check_external=False)
            self.assertEqual(manifest["stats"]["pagesCrawled"], 1)
            self.assertNotIn("domainRegistration", manifest["siteIntel"])
            self.assertEqual((vault / ".obsidian" / "graph.json").read_text(encoding='utf-8'), preferences)
            summary_file = next((vault / "sites").glob("*/_site-summary.json"))
            self.assertNotIn("domainRegistration", json.loads(summary_file.read_text(encoding='utf-8')))
            self.assertTrue(manifest["siteIntel"]["aiReadiness"]["markdownLinkAlternate"])
            self.assertTrue(any(url.endswith("/sitemap.xml") for url in seen))
            self.assertGreater(len(seen), 2)

    def test_disallowed_browser_requests_never_reach_http_client(self):
        class Route:
            aborted = False
            def abort(self):
                self.aborted = True

        class Request:
            url = "https://example.com/data"
            resource_type = "fetch"
            method = "GET"

        handler = make_safe_playwright_route_handler()
        with patch("url_safety.safe_requests_session", side_effect=AssertionError("Should not fetch")):
            for kind in ("fetch", "xhr", "eventsource", "ping", "websocket", "other"):
                route, request = Route(), Request()
                request.resource_type = kind
                handler(route, request)
                self.assertTrue(route.aborted, kind)
            route, request = Route(), Request()
            request.resource_type, request.method = "document", "POST"
            handler(route, request)
            self.assertTrue(route.aborted)

    @NEEDS_BROWSER
    def test_browser_renders_static_content_without_background_apis(self):
        seen = []
        Fixture.hits.clear()
        with self.tripwire(seen):
            result = extractor.fetch_page_html(self.origin + "/render", render_mode="always")
        self.assertIsNone(result["error"], result["error"])
        self.assertTrue(result["render_used"])
        self.assertGreater(len(result["blocked_requests"]), 3)
        self.assertIn("Rendered locally", result["html"])
        self.assertIn("/static.js", Fixture.hits)
        for path in ("/api/data", "/api/post", "/beacon", "/worker.js", "/socket"):
            self.assertNotIn(path, Fixture.hits)
        self.assertEqual(len(seen), 2)

    @NEEDS_BROWSER
    def test_blocked_rendering_is_saved_as_partial(self):
        with tempfile.TemporaryDirectory() as directory, self.tripwire([]), redirect_stdout(io.StringIO()):
            rendered = extractor.fetch_page_html(self.origin + "/render", render_mode="always")
            with patch("page_fetch.PageFetcher.fetch", return_value=rendered):
                manifest = crawl_site.crawl_website_to_vault(self.origin, directory, max_pages=1, download_images=False, render_mode="always", delay_sec=0, check_external=False, parallel=False)
            self.assertEqual(manifest["captureStatus"], "partial")
            self.assertIn("rendering excluded", manifest["captureWarnings"][0])
            site = next((Path(directory) / "sites").iterdir())
            summary = json.loads((site / "_site-summary.json").read_text(encoding='utf-8'))
            self.assertEqual(summary["captureStatus"], "partial")
            self.assertIn("rendering excluded", (site / "_dashboard.md").read_text(encoding='utf-8'))

    @NEEDS_BROWSER
    def test_browser_redirect_cannot_bypass_route_validation(self):
        hits = []
        class Destination(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()
        destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
        thread = threading.Thread(target=destination.serve_forever, daemon=True)
        thread.start()
        Fixture.redirect_target = f"http://127.0.0.1:{destination.server_port}/private"
        try:
            with self.tripwire([]):
                result = extractor.fetch_page_html(self.origin + "/redirect", render_mode="always", timeout_sec=5)
            self.assertTrue(result["error"])
            self.assertEqual(hits, [])
            self.assertTrue(any(row["reason"] == "Browser redirects are disabled" for row in result["blocked_requests"]))
        finally:
            destination.shutdown()
            destination.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
