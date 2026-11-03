#!/usr/bin/env python3
"""Saved-link continuation regressions using temporary vaults and local origins."""
from concurrent.futures import CancelledError, Future
from contextlib import redirect_stdout
from datetime import datetime
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import crawl_site
from link_recheck import continue_link_checks
from provenance import assert_engine_unchanged


class Requests:
    lock = threading.Lock()
    rows = []

    @classmethod
    def add(cls, kind, handler):
        with cls.lock:
            cls.rows.append({"origin": kind, "method": handler.command,
                             "path": handler.path, "range": handler.headers.get("Range")})

    @classmethod
    def clear(cls):
        with cls.lock:
            cls.rows.clear()

    @classmethod
    def snapshot(cls):
        with cls.lock:
            return [dict(row) for row in cls.rows]


class Destinations(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_HEAD(self):
        Requests.add("external", self)
        self.send_response({"/a-ok": 200, "/b-gone": 404, "/c-limited": 403, "/d-error": 503}.get(self.path, 404))
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        Requests.add("external", self)
        self.send_response(404 if self.path == "/b-gone" else 405)
        self.send_header("Content-Length", "0")
        self.end_headers()


class Website(BaseHTTPRequestHandler):
    external_port = 0
    page_count = 2
    version = 1

    def log_message(self, *_args):
        pass

    def respond(self, head):
        Requests.add("website", self)
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/robots.txt":
            body, mime, status = b"User-agent: *\nAllow: /\n", "text/plain", 200
        elif self.path == "/sitemap.xml":
            paths = ["/"] + [f"/page-{number}" for number in range(1, self.page_count)]
            text = "<urlset>" + "".join(f"<url><loc>{origin}{path}</loc></url>" for path in paths) + "</urlset>"
            body, mime, status = text.encode(), "application/xml", 200
        elif self.path == "/images/hero.png":
            body, mime, status = b"\x89PNG\r\n\x1a\nfixture-image-body", "image/png", 200
        elif self.path == "/handbook.pdf":
            body, mime, status = b"%PDF-1.7\nfixture-document-body", "application/pdf", 200
        elif self.path == "/" or self.path.startswith("/page-"):
            text = "Alpha source sentence." if self.version == 1 else "Bravo source sentence."
            external = "".join(f'<a href="http://localhost:{self.external_port}{path}">{path}</a>'
                               for path in ("/a-ok", "/b-gone", "/c-limited", "/d-error"))
            html = ('<html lang="en"><head><title>Local continuation fixture</title>'
                    '<meta name="description" content="Retained source for local link checks."></head>'
                    '<body><main><h1>Source business</h1><p>' + text + " " + "Verifiable page text. " * 25
                    + '</p><img src="/images/hero.png" alt="Published image">'
                    '<a href="/handbook.pdf">Published handbook</a>' + external + "</main></body></html>")
            body, mime, status = html.encode(), "text/html", 200
        else:
            body, mime, status = b"Not found", "text/plain", 404
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self):
        self.respond(False)

    def do_HEAD(self):
        self.respond(True)


def digest_files(root):
    return {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in root.rglob("*") if file.is_file()}


class FailingCloseDispatcher:
    """Return a result and stage robots bytes, then fail before publication."""
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def submit(self, operation, payload, **_kwargs):
        if operation != "link":
            raise AssertionError("Continuation must submit only link operations")
        raw = b"User-agent: *\nAllow: /\n"
        future = Future()
        future.set_result({"url": payload["url"], "status": "ok", "statusCode": 200,
                           "attempted": True, "reason": "Synthetic HEAD result", "method": "HEAD",
                           "robots_receipts": {"https://fixture.invalid": {
                               "raw_bytes": raw, "sha256": hashlib.sha256(raw).hexdigest()}}})
        return future

    def __exit__(self, *_args):
        raise RuntimeError("Synthetic dispatcher cleanup failure")


class CancelledDispatcher(FailingCloseDispatcher):
    def submit(self, operation, payload, **_kwargs):
        if operation != "link":
            raise AssertionError("Continuation must submit only link operations")
        future = Future()
        future.set_exception(CancelledError("Synthetic continuation cancellation"))
        return future

    def __exit__(self, *_args):
        return False


class LinkContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.external = ThreadingHTTPServer(("127.0.0.1", 0), Destinations)
        cls.website = ThreadingHTTPServer(("127.0.0.1", 0), Website)
        Website.external_port = cls.external.server_port
        cls.threads = [threading.Thread(target=server.serve_forever, daemon=True)
                       for server in (cls.external, cls.website)]
        for thread in cls.threads:
            thread.start()
        cls.origin = f"http://127.0.0.1:{cls.website.server_port}"
        cls.environment = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS":
            f"127.0.0.1:{cls.website.server_port},localhost:{cls.external.server_port}",
            "CLAUDE_SEO_LOCAL_TARGETS": ""})
        cls.environment.start()

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        for server in (cls.external, cls.website):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(2)

    def setUp(self):
        Website.page_count, Website.version = 2, 1
        Requests.clear()

    def capture(self, directory):
        with redirect_stdout(io.StringIO()):
            return crawl_site.crawl_website_to_vault(self.origin, directory, max_pages=20,
                render_mode="never", download_images=False, delay_sec=0,
                check_external=False, parallel=False)

    def run_checks(self, before, directory, **kwargs):
        events = []
        manifest = continue_link_checks(before["siteId"], directory,
            lambda event, **data: events.append({"event": event, **data}), **kwargs)
        self.assertEqual(events[-1]["event"], "complete")
        self.assertEqual(events[-1]["operation"], "continue-links")
        return manifest

    def test_continuation_heads_remaining_targets_without_recrawling_pages_or_media(self):
        with tempfile.TemporaryDirectory() as directory:
            before = self.capture(directory)
            # Retain one actual HEAD result, then resume the remaining inventory.
            before = self.run_checks(before, directory, max_checks=1, max_seconds=30)
            unchecked = {row["url"] for row in before["linkHealth"]["results"] if row["status"] == "unchecked"}
            checked = {row["url"]: row for row in before["linkHealth"]["results"] if row["status"] != "unchecked"}
            self.assertGreater(len(unchecked), 0)
            self.assertGreater(len(checked), 0)
            site = Path(directory) / "sites" / before["siteId"]
            retained = {name: digest for name, digest in digest_files(site).items()
                        if name.startswith(("pages/", "assets/")) or name.endswith(".html")}
            Requests.clear()
            after = self.run_checks(before, directory, max_seconds=30)
            trace = Requests.snapshot()
            self.assertEqual(after["capturedAt"], before["capturedAt"])
            self.assertEqual(after["stats"], before["stats"])
            self.assertEqual(after["captureProvenance"], before["captureProvenance"])
            self.assertEqual(after["linkHealth"]["uncheckedCount"], 0)
            self.assertGreaterEqual(datetime.fromisoformat(after["linkHealth"]["updatedAt"]),
                                    datetime.fromisoformat(before["capturedAt"].replace("Z", "+00:00")))
            rows = {row["url"]: row for row in after["linkHealth"]["results"]}
            for url, row in checked.items():
                self.assertEqual(rows[url], row)
            for url in unchecked:
                self.assertEqual(rows[url]["method"], "GET" if url.endswith("/b-gone") else "HEAD")
                self.assertIn("checkedAt", rows[url])
            self.assertTrue(any(row["method"] == "HEAD" for row in trace))
            self.assertTrue(all(row["method"] == "HEAD" or row["path"] == "/robots.txt" or row["path"] == "/b-gone" and row["range"] == "bytes=0-1024" for row in trace), trace)
            self.assertEqual(retained, {name: digest_files(site)[name] for name in retained})
            session = after["linkCheckSessions"][-1]
            self.assertEqual(session["targetsSubmitted"], len(unchecked))
            self.assertEqual(session["provenance"]["configuration"]["operation"], "continue-links")
            Requests.clear()
            no_work = self.run_checks(after, directory, max_seconds=30)
            self.assertEqual(Requests.snapshot(), [])
            self.assertEqual(no_work["linkCheckSessions"][-1]["targetsSubmitted"], 0)
            self.assertEqual(no_work["capturedAt"], before["capturedAt"])
            self.assertEqual(no_work["linkHealth"]["results"], after["linkHealth"]["results"])

    def test_per_run_cap_leaves_other_targets_available_for_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            before = self.capture(directory)
            original_unchecked = before["linkHealth"]["uncheckedCount"]
            self.assertGreater(original_unchecked, 1)
            Requests.clear()
            after = self.run_checks(before, directory, max_checks=1, max_seconds=30)
            self.assertEqual(after["linkCheckSessions"][-1]["targetsSubmitted"], 1)
            self.assertEqual(after["linkHealth"]["uncheckedCount"], original_unchecked - 1)
            self.assertEqual(sum(row["method"] == "HEAD" for row in Requests.snapshot()), 1)
            previous_rows = {row["url"]: row for row in after["linkHealth"]["results"] if row["status"] != "unchecked"}
            finished = self.run_checks(after, directory, max_seconds=30)
            self.assertEqual(finished["linkHealth"]["uncheckedCount"], 0)
            for row in finished["linkHealth"]["results"]:
                if row["url"] in previous_rows:
                    self.assertEqual(row, previous_rows[row["url"]])

    def test_member_files_and_generated_baseline_survive_continuation_and_recapture(self):
        with tempfile.TemporaryDirectory() as directory:
            before = self.capture(directory)
            site = Path(directory) / "sites" / before["siteId"]
            inventory_before = json.loads((site / "_generated-files.json").read_text())["files"]
            note = site / "pages/index.md"
            edited = note.read_bytes() + b"\nMember annotation that must survive.\n"
            note.write_bytes(edited)
            (site / "member.txt").write_bytes(b"Untracked member file")
            (site / "pages/member.md").write_bytes(b"# Member-created note\n")
            self.run_checks(before, directory, max_seconds=30)
            self.assertEqual(note.read_bytes(), edited)
            inventory_after = json.loads((site / "_generated-files.json").read_text())["files"]
            self.assertEqual(inventory_after["pages/index.md"]["generatedSha256"],
                             inventory_before["pages/index.md"]["generatedSha256"])
            self.assertNotIn("member.txt", inventory_after)
            self.assertNotIn("pages/member.md", inventory_after)
            Website.version = 2
            recaptured = self.capture(directory)
            self.assertEqual(note.read_bytes(), edited)
            self.assertEqual((site / "member.txt").read_bytes(), b"Untracked member file")
            self.assertEqual((site / "pages/member.md").read_bytes(), b"# Member-created note\n")
            node = next(node for node in recaptured["nodes"] if node["obsidianPath"].endswith("/pages/index.md"))
            self.assertEqual(node["noteStatus"], "preserved-local-edits")
            proposal = Path(directory) / node["proposedNotePath"]
            self.assertTrue(proposal.is_file())
            self.assertNotIn(b"Member annotation", proposal.read_bytes())

    def test_cancelled_dispatcher_result_rolls_back_saved_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            before = self.capture(directory)
            site = Path(directory) / "sites" / before["siteId"]
            saved = digest_files(site)
            events = []
            with self.assertRaises(CancelledError):
                continue_link_checks(before["siteId"], directory,
                    lambda event, **data: events.append({"event": event, **data}),
                    max_checks=1, dispatcher_class=CancelledDispatcher)
            self.assertEqual(digest_files(site), saved)
            self.assertFalse(any(row["event"] == "complete" for row in events))

    def test_fatal_dispatcher_cleanup_error_rolls_back_staged_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            before = self.capture(directory)
            site = Path(directory) / "sites" / before["siteId"]
            saved = digest_files(site)
            events = []
            with self.assertRaisesRegex(RuntimeError, "Synthetic dispatcher cleanup failure"):
                continue_link_checks(before["siteId"], directory,
                    lambda event, **data: events.append({"event": event, **data}),
                    max_checks=1, dispatcher_class=FailingCloseDispatcher)
            self.assertEqual(digest_files(site), saved)
            self.assertFalse(any(row["event"] == "complete" for row in events))

    def test_engine_source_fence_failure_preserves_saved_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            before = self.capture(directory)
            site = Path(directory) / "sites" / before["siteId"]
            saved = digest_files(site)
            events = []
            Requests.clear()
            with patch("link_recheck.assert_engine_unchanged",
                       side_effect=RuntimeError("Synthetic engine source changed")) as fence:
                with self.assertRaisesRegex(RuntimeError, "Synthetic engine source changed"):
                    continue_link_checks(before["siteId"], directory,
                        lambda event, **data: events.append({"event": event, **data}),
                        max_checks=1, max_seconds=30)
            fence.assert_called_once()
            self.assertEqual(fence.call_args.args[0]["configuration"]["operation"], "continue-links")
            self.assertEqual(sum(row["method"] == "HEAD" for row in Requests.snapshot()), 1)
            self.assertEqual(digest_files(site), saved)
            self.assertFalse(any(row["event"] == "complete" for row in events))
            self.assertEqual(list((Path(directory) / ".web-obs" / "staging").iterdir()), [])

    def test_engine_source_fence_rejects_changed_hash_without_editing_sources(self):
        with patch("provenance.capture_provenance", return_value={"engineSha256": "new-identity"}):
            with self.assertRaisesRegex(RuntimeError, "Engine source changed during collection"):
                assert_engine_unchanged({"engineSha256": "original-identity"})
        with patch("provenance.capture_provenance", return_value={"engineSha256": "same-identity"}):
            assert_engine_unchanged({"engineSha256": "same-identity"})

    def test_unsafe_site_ids_are_rejected_before_creating_capture_state(self):
        with tempfile.TemporaryDirectory() as directory:
            for unsafe in ("../escape", ".", "..", "/tmp/site", "bad\\id", "nested/site", "", "a" * 181, None, 7):
                with self.subTest(site_id=unsafe), self.assertRaises(ValueError):
                    continue_link_checks(unsafe, directory, lambda *_args, **_kwargs: None)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_capture_provenance_and_eight_page_sample_coverage_are_explicit(self):
        Website.page_count = 12
        with tempfile.TemporaryDirectory() as directory:
            capture = self.capture(directory)
            provenance = capture["captureProvenance"]
            configuration = provenance["configuration"]
            for key, value in {"maxPages": 20, "downloadImages": False, "renderMode": "never",
                               "delaySec": 0, "checkExternal": False, "parallel": False}.items():
                self.assertEqual(configuration[key], value)
            hashes = provenance["engineFiles"]
            self.assertIn("crawl_site.py", hashes)
            self.assertIn("link_recheck.py", hashes)
            self.assertTrue(all(len(digest) == 64 for digest in hashes.values()))
            identity = "\n".join(f"{name}:{digest}" for name, digest in sorted(hashes.items()))
            self.assertEqual(provenance["engineSha256"], hashlib.sha256(identity.encode()).hexdigest())
            self.assertIn("pythonVersion", provenance["runtime"])
            self.assertIn("requests", provenance["runtime"]["packages"])
            coverage = capture["siteIntel"]["techStack"]["coverage"]
            self.assertEqual(coverage["capturedHtmlPages"], 12)
            self.assertEqual(coverage["sampledPages"], 8)
            self.assertEqual(len(set(coverage["sourceUrls"])), 8)
            captured_urls = {node["url"] for node in capture["nodes"] if node["kind"] != "external-domain"}
            self.assertTrue(set(coverage["sourceUrls"]).issubset(captured_urls))
            self.assertEqual(coverage["sourceUrls"][0], self.origin + "/")
            self.assertEqual(coverage["securityHeadersScope"], "Homepage response, with consistency checked across sampled pages")


if __name__ == "__main__":
    unittest.main(verbosity=2)
