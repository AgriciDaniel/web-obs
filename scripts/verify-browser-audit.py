#!/usr/bin/env python3
"""Browser audit: JavaScript content gap, lab timings, axe-core, screenshots and third parties, on local fixtures only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import browser_audit
from browser_audit import build_findings, categorize_host, js_gap, js_gap_reasons, run_browser_audit, screenshot_name

RAW_HOME = """<!doctype html><html lang="en"><head><title>Fixture</title></head><body>
<main><p>Short raw text.</p><div id="app"></div></main>
<img src="/missing-alt.png">
<script src="/app.js"></script>
<script src="http://localhost:{third}/tracker.js"></script>
</body></html>"""

APP_JS = """
const app = document.getElementById('app');
const h = document.createElement('h1'); h.textContent = 'Rendered heading'; app.appendChild(h);
for (let i = 0; i < 60; i++) { const p = document.createElement('p'); p.textContent = 'Rendered word number ' + i + ' adds visible content here.'; app.appendChild(p); }
for (let i = 0; i < 8; i++) { const a = document.createElement('a'); a.href = '/page-' + i; a.textContent = 'Link ' + i; app.appendChild(a); }
const s = document.createElement('script'); s.type = 'application/ld+json'; s.textContent = JSON.stringify({'@context': 'https://schema.org', '@type': 'Organization', name: 'Fixture'}); document.head.appendChild(s);
document.cookie = 'fixture_pref=1; path=/; SameSite=Lax';
"""


class Site(BaseHTTPRequestHandler):
    third_port = 0
    hits: list = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).hits.append(self.path)
        if self.path == "/":
            body, kind = RAW_HOME.format(third=type(self).third_port), "text/html"
        elif self.path == "/app.js":
            body, kind = APP_JS, "application/javascript"
        elif self.path == "/missing-alt.png":
            self.send_response(404)
            self.end_headers()
            return
        else:
            body, kind = "<html><body><h1>Other</h1></body></html>", "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


class ThirdParty(BaseHTTPRequestHandler):
    hits: list = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.end_headers()
        self.wfile.write(b"window.__tracked = true;")


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        from browser_runtime import resolve_chromium_executable
        with sync_playwright() as driver:
            return bool(resolve_chromium_executable(driver).get("executablePath"))
    except Exception:
        return False


NEEDS_BROWSER = unittest.skipUnless(chromium_available(), "No compatible Chromium found, skipping browser audit test.")


class PureTests(unittest.TestCase):
    def test_js_gap_measures_words_links_schema_and_h1(self):
        raw = "<html><body><p>one two</p></body></html>"
        rendered = ('<html><head><script type="application/ld+json">{"@type": ["Organization", "Brand"]}</script></head>'
                    "<body><h1>Title here</h1>" + "<p>word word word word word</p>" * 10 + '<a href="/a">a</a>' * 6 + "</body></html>")
        gap = js_gap(raw, rendered)
        self.assertEqual(gap["rawWords"], 2)
        self.assertGreater(gap["renderedWords"], 40)
        self.assertGreaterEqual(gap["wordsAddedByJsPct"], 90)
        self.assertEqual(gap["renderedSchemaTypes"], ["Organization", "Brand"])
        reasons = js_gap_reasons(gap)
        self.assertEqual(len(reasons), 4, reasons)
        self.assertIsNone(js_gap(None, rendered))
        self.assertEqual(js_gap_reasons(js_gap(rendered, rendered)), [])

    def test_host_categories_and_screenshot_names(self):
        self.assertEqual(categorize_host("www.google-analytics.com"), "analytics")
        self.assertEqual(categorize_host("connect.facebook.net"), "ads")
        self.assertEqual(categorize_host("platform.twitter.com"), "social")
        self.assertEqual(categorize_host("cdn.jsdelivr.net"), "cdn")
        self.assertEqual(categorize_host("example.org"), "other")
        self.assertRegex(screenshot_name("https://a.test/"), r"^home-[0-9a-f]{6}\.jpg$")
        self.assertRegex(screenshot_name("https://a.test/Blog/Post_1"), r"^blog-post-1-[0-9a-f]{6}\.jpg$")

    def test_findings_follow_the_shared_shape(self):
        pages = [{"url": "https://a.test/", "jsGap": {"rawWords": 1, "renderedWords": 100, "rawLinks": 0, "renderedLinks": 0,
                  "rawSchemaTypes": [], "renderedSchemaTypes": [], "rawH1": [], "renderedH1": [], "wordsAddedByJsPct": 99},
                  "lab": {"lcpMs": 5200}, "a11y": {"violations": [{"id": "image-alt", "impact": "critical", "help": "Images must have alternative text", "nodes": 2}]},
                  "thirdParty": {"hosts": [{"host": "t.test", "requests": 1, "category": "other"}]}}]
        findings = {f["id"]: f for f in build_findings(pages)}
        self.assertEqual(set(findings), {"js-dependent-content", "slow-lab-lcp", "a11y-image-alt", "third-party-before-interaction"})
        for finding in findings.values():
            self.assertEqual(finding["category"], "browser")
            self.assertIn(finding["tone"], ("attention", "review", "coverage"))
            self.assertTrue(finding["targets"][0]["url"] and finding["targets"][0]["detail"])
        self.assertIn("2 elements", findings["a11y-image-alt"]["targets"][0]["detail"])

    def test_skips_cleanly_without_browser_or_when_rendering_is_off(self):
        self.assertEqual(run_browser_audit(["https://a.test/"], site_root="/nonexistent", domain_folder="a.test", render_mode="never")["state"], "skipped")
        self.assertEqual(run_browser_audit([], site_root="/nonexistent", domain_folder="a.test")["state"], "skipped")
        with patch.object(browser_audit, "sync_playwright", None):
            result = run_browser_audit(["https://a.test/"], site_root="/nonexistent", domain_folder="a.test")
        self.assertEqual(result["state"], "skipped")
        self.assertIn("Playwright", result["detail"])
        self.assertEqual(result["pages"], [])

    def test_vendored_axe_is_present_and_licensed(self):
        vendor = ROOT / "engine" / "vendor"
        self.assertTrue((vendor / "axe.min.js").read_text(encoding="utf-8").startswith("/*! axe v4."))
        self.assertIn("Mozilla Public License", (vendor / "axe-core-LICENSE.txt").read_text(encoding="utf-8"))


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.third = ThreadingHTTPServer(("127.0.0.1", 0), ThirdParty)
        Site.third_port = cls.third.server_port
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        cls.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (cls.site, cls.third)]
        for thread in cls.threads:
            thread.start()
        cls.origin = f"http://127.0.0.1:{cls.site.server_port}"
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.site.server_port},localhost:{cls.third.server_port}"})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.site, cls.third):
            server.shutdown()
            server.server_close()
        cls.env.stop()

    @NEEDS_BROWSER
    def test_audit_of_a_local_page(self):
        home = self.origin + "/"
        raw = RAW_HOME.format(third=self.third.server_port)
        with tempfile.TemporaryDirectory() as directory:
            result = run_browser_audit([home, home, "ftp://ignored"], site_root=directory, domain_folder="fixture",
                                       raw_html_by_url={home: raw}, time_budget_sec=60, per_page_sec=30)
            self.assertEqual(result["state"], "ok", result)
            self.assertEqual(result["sampledUrls"], [home])
            page = result["pages"][0]
            self.assertIsNone(page["error"])
            gap = page["jsGap"]
            self.assertGreaterEqual(gap["wordsAddedByJsPct"], 30)
            self.assertEqual(gap["renderedH1"], ["Rendered heading"])
            self.assertIn("Organization", gap["renderedSchemaTypes"])
            self.assertIsNotNone(page["screenshot"])
            shot = Path(directory) / page["screenshot"]
            self.assertTrue(shot.is_file() and shot.read_bytes()[:2] == b"\xff\xd8")
            lab = page["lab"]
            self.assertGreaterEqual(lab["loadMs"], 0)
            self.assertGreater(lab["requests"], 1)
            self.assertIn("Not field data", lab["note"])
            self.assertEqual(page["a11y"]["state"], "ok", page["a11y"])
            self.assertTrue(page["a11y"]["engine"].startswith("axe-core 4."))
            self.assertIn("image-alt", {v["id"] for v in page["a11y"]["violations"]})
            hosts = {h["host"] for h in page["thirdParty"]["hosts"]}
            self.assertIn("localhost", hosts)
            cookies = {c["name"]: c for c in page["thirdParty"]["cookies"]}
            self.assertTrue(cookies["fixture_pref"]["firstParty"])
            ids = {f["id"] for f in result["findings"]}
            self.assertTrue({"js-dependent-content", "a11y-image-alt", "third-party-before-interaction"} <= ids, ids)

    @NEEDS_BROWSER
    def test_policy_refusal_is_recorded_not_raised(self):
        home = self.origin + "/"
        with tempfile.TemporaryDirectory() as directory:
            result = run_browser_audit([home], site_root=directory, domain_folder="fixture",
                                       allow_url=lambda _url: False, time_budget_sec=20)
        self.assertEqual(result["state"], "skipped")
        self.assertIn("policy", result["pages"][0]["error"])
        self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
