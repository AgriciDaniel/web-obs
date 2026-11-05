"""The per-run switches a host app uses to run a fixed capture plan:
--no-tls-check, --no-tasks, --deadline SECONDS, and the renamed robots product name.

Offline: the fixture site is served on 127.0.0.1 and allowed through WEB_OBS_LOCAL_TARGETS.
"""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(ENGINE))
import crawl_site  # noqa: E402
import site_intel  # noqa: E402
import transport_checks  # noqa: E402
import url_safety  # noqa: E402

PAGES = 30


class Site(BaseHTTPRequestHandler):
    page_delay = 0.0
    robots_delay = 0.0
    requests: list[tuple[float, str]] = []
    lock = threading.Lock()

    def do_GET(self):
        with Site.lock:
            Site.requests.append((time.monotonic(), self.path))
        path = self.path.split("?", 1)[0]
        if path == "/robots.txt":
            time.sleep(Site.robots_delay)
            return self.reply("User-agent: *\nAllow: /\n", "text/plain")
        if path == "/sitemap.xml":
            urls = "".join(f"<url><loc>{self.origin()}/p/{i}</loc></url>" for i in range(PAGES))
            return self.reply(f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{self.origin()}/</loc></url>{urls}</urlset>', "application/xml")
        if path == "/" or path.startswith("/p/"):
            if path != "/":
                time.sleep(Site.page_delay)
            links = "".join(f'<li><a href="/p/{i}">Page {i}</a></li>' for i in range(PAGES))
            return self.reply(f"<!doctype html><html lang=en><head><title>Fixture {path}</title><meta name=description content='A fixture page for switch tests.'></head>"
                              f"<body><header><a href='/'>Fixture</a></header><main><h1>Fixture {path}</h1><p>{'Words for the page body. ' * 40}</p><ul>{links}</ul></main></body></html>",
                              "text/html; charset=utf-8")
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def reply(self, body: str, kind: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the capture hung up at its deadline, which is what these tests exercise

    def log_message(self, *_args):
        pass


class CaptureSwitches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.server.server_port}", "CLAUDE_SEO_LOCAL_TARGETS": ""})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Site.page_delay, Site.robots_delay = 0.0, 0.0
        Site.requests = []

    def capture(self, directory, **options):
        settings = dict(max_pages=PAGES + 1, render_mode="never", download_images=False, delay_sec=0,
                        check_external=False, parallel=False, browser_audit=False, snapshot_limit=0, dns_checks=False)
        settings.update(options)
        with redirect_stdout(io.StringIO()):
            manifest = crawl_site.crawl_website_to_vault(self.origin, directory, **settings)
        return manifest, Path(directory) / "sites" / manifest["siteId"]

    def test_tasks_are_written_by_default_and_not_with_no_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, site = self.capture(directory, max_pages=3)
            self.assertTrue((site / "_tasks.md").is_file())
            self.assertIsNotNone(manifest["audit"]["tasks"])
        with tempfile.TemporaryDirectory() as directory:
            manifest, site = self.capture(directory, max_pages=3, tasks=False)
            self.assertFalse((site / "_tasks.md").exists())
            self.assertIsNone(manifest["audit"]["tasks"])
            self.assertNotIn("_tasks|Task list", (site / "_audit.md").read_text(encoding="utf-8"))
            self.assertNotIn("_tasks|Task list", (site / "_dashboard.md").read_text(encoding="utf-8"))
            self.assertFalse(manifest["captureProvenance"]["configuration"]["tasks"], "the run records that tasks were off")

    def test_no_tls_check_makes_no_handshake(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("transport_checks.check_tls_certificate", side_effect=AssertionError("TLS check ran")) as tls:
            manifest, _site = self.capture(directory, max_pages=3, tls_check=False)
            tls.assert_not_called()
            state = manifest["siteIntel"]["transport"]["tls"]
            self.assertEqual(state["state"], "skipped")
            self.assertIn("turned off", state["detail"])
            self.assertFalse(any(f["id"].startswith("tls-") for f in manifest["audit"]["findings"]))

    def assert_no_request_after(self, deadline_at: float, slack: float = 0.3):
        late = [(round(at - deadline_at, 2), path) for at, path in Site.requests if at > deadline_at + slack]
        self.assertEqual(late, [], "requests started after the capture deadline")

    def test_deadline_stops_page_collection_and_marks_the_capture_partial(self):
        Site.page_delay = 0.4
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            manifest, site = self.capture(directory, deadline_sec=3.0)
            self.assert_no_request_after(started + 3.0)
            self.assertEqual(manifest["captureStatus"], "partial")
            warnings = " ".join(manifest["captureWarnings"])
            self.assertIn("capture deadline was reached during collection", warnings)
            self.assertIn("before the certificate check", warnings)
            pages = [n for n in manifest["nodes"] if n["kind"] != "external-domain"]
            self.assertLess(len(pages), PAGES + 1, "the deadline cut the crawl short")
            self.assertGreater(len(pages), 0, "what was collected in time is kept")
            self.assertFalse([n["url"] for n in pages if n["health"] in ("broken", "unavailable")],
                             "pages cut short by the deadline are not reported as broken")
            self.assertTrue((site / "_site-graph.json").is_file(), "the capture is still saved")
            self.assertEqual(manifest["captureProvenance"]["configuration"]["deadlineSec"], 3.0)
        self.assertIsNone(url_safety.capture_deadline(), "the deadline is cleared after the capture")

    def test_deadline_also_bounds_parallel_workers(self):
        Site.page_delay = 0.4
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            manifest, _site = self.capture(directory, deadline_sec=5.0, parallel=True)
            self.assert_no_request_after(started + 5.0)
            self.assertEqual(manifest["captureStatus"], "partial")
            self.assertIn("capture deadline", " ".join(manifest["captureWarnings"]))
            pages = [n for n in manifest["nodes"] if n["kind"] != "external-domain"]
            self.assertFalse([n["url"] for n in pages if n["health"] in ("broken", "unavailable")],
                             "spawned workers also report deadline cuts as unfinished, not broken")

    def test_a_request_cut_by_the_capture_deadline_says_so(self):
        Site.page_delay = 2.0
        url_safety.set_capture_deadline(time.monotonic() + 0.6)
        try:
            with self.assertRaises(url_safety.RequestDeadlineExceeded) as raised:
                url_safety.safe_requests_get(f"{self.origin}/p/1", timeout=10)
            self.assertIn("Capture deadline", str(raised.exception))
            self.assertTrue(url_safety.capture_out_of_time(1.0))
        finally:
            url_safety.set_capture_deadline(None)
        self.assertFalse(url_safety.capture_out_of_time(1.0), "no deadline means never out of time")

    def test_deadline_inside_the_robots_phase_still_saves_a_capture(self):
        Site.robots_delay = 2.5
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            manifest, site = self.capture(directory, deadline_sec=1.0)
            self.assert_no_request_after(started + 1.0)
            self.assertEqual(manifest["captureStatus"], "partial")
            self.assertTrue((site / "_site-graph.json").is_file())
            warnings = " ".join(manifest["captureWarnings"])
            self.assertIn("deadline was reached while reading robots.txt and sitemaps", warnings)
            self.assertNotIn("skipped by robots policy", warnings, "a robots.txt read the deadline cut is not blamed on the site")

    def test_dns_check_respects_its_total_budget(self):
        class SlowResolver:
            def resolve(self, _name, _kind):
                time.sleep(0.2)
                raise transport_checks.DNSNoRecord()
        started = time.monotonic()
        result = transport_checks.check_email_dns("brand.example", resolver=SlowResolver(), budget_sec=0.5)
        self.assertLess(time.monotonic() - started, 1.0, "about a dozen queries are cut off by the budget")
        self.assertEqual(result["state"], "unreachable")

    def test_robots_product_name_keeps_its_value_and_manifest_key(self):
        self.assertEqual(site_intel.ROBOTS_PRODUCT_NAME, "WebObs")
        self.assertFalse(hasattr(site_intel, "ROBOTS_PRODUCT_TOKEN"))
        source = (ENGINE / "site_intel.py").read_text(encoding="utf-8")
        self.assertIn('"productToken": ROBOTS_PRODUCT_NAME', source, "the manifest key stays productToken for existing readers")

    def test_cli_flags(self):
        help_text = subprocess.run([sys.executable, str(ENGINE / "crawl_site.py"), "--help"], capture_output=True, text=True, timeout=60).stdout
        for flag in ("--no-tls-check", "--no-tasks", "--deadline SECONDS"):
            self.assertIn(flag, help_text)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(ENGINE / "crawl_site.py"), "--vault", directory, "--deadline", "0", self.origin],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 2)
        self.assertIn("--deadline must be between 1 and 86400 seconds", run.stdout)

    def test_plugin_and_local_api_pass_each_switch(self):
        root = ENGINE.parent / "src"
        view = (root / "plugin" / "SiteGlobeView.ts").read_text(encoding="utf-8")
        api = (root / "server" / "captureApi.ts").read_text(encoding="utf-8")
        settings = (root / "plugin" / "settings.ts").read_text(encoding="utf-8")
        types = (root / "types" / "site.ts").read_text(encoding="utf-8")
        for flag in ("'--no-tls-check'", "'--no-tasks'", "'--deadline'"):
            self.assertIn(flag, view, f"the plugin passes {flag}")
            self.assertIn(flag, api, f"the local capture API passes {flag}")
        for key, default in (("tlsCheck", "true"), ("taskList", "true"), ("captureDeadlineMinutes", "0")):
            self.assertIn(f"  {key}: {default},", settings, f"{key} defaults to {default}, so existing setups behave as before")
            self.assertIn(f"this.bridge.settings.{key}", settings, f"{key} has a control in the settings tab")
        for key in ("tlsCheck?: boolean", "taskList?: boolean", "deadlineSec?: number"):
            self.assertIn(key, types)


if __name__ == "__main__":
    unittest.main(verbosity=1)
