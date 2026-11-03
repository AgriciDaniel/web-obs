#!/usr/bin/env python3
"""Behavioral tests for local evidence exports; no public website is contacted."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import evidence_export
import brand_and_dns


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "_raw").mkdir()
        self.html = ('<html><head><title>Observed Business</title><meta name="description" content="Source description">'
                     '<style>.warning {color:#ff0000} body {background:#ffffff}</style></head><body><h1>Measured source</h1>'
                     '<p>' + 'Verifiable local source text. ' * 25 + '</p><a href="/contact">Contact us</a></body></html>')
        self.raw = self.html.encode()
        self.path = self.root / "_raw" / "home.html"
        self.path.write_bytes(self.raw)
        self.row = {"url": "https://fixture.example/", "path": "/", "statusCode": 200,
                    "responseTimeMs": 45, "htmlBytes": len(self.raw), "visibleChars": 700,
                    "rawPath": "_raw/home.html", "rawSha256": hashlib.sha256(self.raw).hexdigest(),
                    "rawKind": "http-response", "robotsPolicy": "allowed", "redirectChain": []}

    def tearDown(self):
        self.temp.cleanup()

    def receipt(self, **updates):
        return evidence_export.write_fetch_log(str(self.root), "fixture.example", "https://fixture.example", "2026-11-01", [{**self.row, **updates}])["entries"][0]

    def test_receipt_requires_matching_retained_bytes(self):
        self.assertTrue(self.receipt()["dataEligible"])
        self.path.write_bytes(self.raw + b"changed")
        self.assertFalse(self.receipt()["dataEligible"])
        self.assertIn("SHA-256", ";".join(self.receipt()["exclusions"]))

    def test_receipt_unknown_and_failed_evidence_never_default_to_allowed(self):
        for updates in ({"robotsPolicy": None}, {"robotsPolicy": "unknown"}, {"robotsPolicy": "disallowed"},
                        {"statusCode": 503}, {"statusCode": None}, {"visibleChars": 199},
                        {"error": "timeout"}, {"redirectChain": [{"statusCode": 301}]},
                        {"rawPath": "../private.txt"}, {"rawSha256": None}):
            with self.subTest(updates=updates):
                self.assertEqual(self.receipt(**updates)["dataState"], "no data")
        self.assertNotIn("TTFB", (self.root / "_fetch-log.md").read_text(encoding="utf-8"))

    def test_symlink_escape_does_not_become_evidence(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_bytes(self.raw)
        try:
            (self.root / "_raw" / "linked.html").symlink_to(outside)
            self.assertFalse(self.receipt(rawPath="_raw/linked.html")["artifactVerified"])
        finally:
            outside.unlink()

    def test_dom_evidence_class_is_retained(self):
        row = self.receipt(rawKind="rendered-dom", renderUsed=True)
        self.assertEqual(row["rawKind"], "rendered-dom")
        self.assertTrue(row["dataEligible"])

    def test_non_utf8_source_requires_verified_text_sidecar(self):
        text = self.html.replace("Observed Business", "Café Business")
        raw = text.encode("iso-8859-1")
        self.path.write_bytes(raw)
        self.row.update(rawSha256=hashlib.sha256(raw).hexdigest(), htmlBytes=len(raw))
        self.assertFalse(self.receipt()["dataEligible"])
        sidecar = self.root / "_raw" / "home.utf8.html"
        sidecar.write_bytes(text.encode("utf-8"))
        self.row.update(textPath="_raw/home.utf8.html", textSha256=hashlib.sha256(sidecar.read_bytes()).hexdigest())
        self.assertTrue(self.receipt()["dataEligible"])
        result = self.pack()
        self.assertGreater(result["observationsCount"], 0)
        output = (self.root / "_evidence-pack.md").read_text(encoding="utf-8")
        self.assertIn("Café Business", output)
        self.assertNotIn(chr(0xfffd), output)
        self.assertIn("locator `_raw/home.utf8.html:", output)
        self.assertIn("original body `_raw/home.html`", output)
        self.assertIn("class `decoded-text`", output)
        sidecar.write_text("tampered text", encoding='utf-8')
        self.assertFalse(self.receipt()["dataEligible"])
        self.assertEqual(self.pack()["observationsCount"], 0)

    def test_decoded_brand_tokens_require_original_body_anchor(self):
        sidecar = self.root / "_raw" / "home.utf8.html"
        sidecar.write_text(self.html, encoding='utf-8')
        brand = brand_and_dns.extract_observed_brand_kit(self.html, self.row["url"], source_artifacts={self.row["url"]: {
            "rawPath": "_raw/home.utf8.html", "rawSha256": hashlib.sha256(sidecar.read_bytes()).hexdigest(),
            "rawKind": "decoded-text", "parentRawPath": self.row["rawPath"], "parentRawSha256": self.row["rawSha256"]}})
        result = evidence_export.write_evidence_pack(str(self.root), "fixture.example", "fixture.example", "Brand", "https://fixture.example", "now", {}, brand, {}, {}, {}, fetch_rows=[self.row], page_records=[])
        self.assertGreater(result["designObservationsCount"], 0)
        self.path.write_bytes(b"original body changed")
        result = evidence_export.write_evidence_pack(str(self.root), "fixture.example", "fixture.example", "Brand", "https://fixture.example", "now", {}, brand, {}, {}, {}, fetch_rows=[self.row], page_records=[])
        self.assertEqual(result["designObservationsCount"], 0)

    def test_pagerank_is_relative_and_independent_of_home_label(self):
        urls = ["a", "b", "c"]
        edges = {("a", "b"): {"zones": {"body"}}, ("c", "b"): {"zones": {"body"}}}
        scores = evidence_export.compute_internal_pagerank(urls, edges, "a")
        self.assertEqual(scores, evidence_export.compute_internal_pagerank(urls, edges, "c"))
        self.assertGreater(scores["b"], scores["a"])
        self.assertEqual(evidence_export.compute_internal_pagerank(["a"], {}, "a"), {"a": 50})

    def test_bases_filters_are_structured_and_only_emitted_properties_are_used(self):
        base = json.loads(evidence_export.build_pages_base_yaml("fixture.example", "fixture.example", "2026-11-01"))
        audit = next(view for view in base["views"] if view["name"] == "SEO Audit Queue")
        def valid(filter_value):
            if isinstance(filter_value, str):
                return True
            return len(filter_value) == 1 and next(iter(filter_value)) in ("and", "or", "not") and all(valid(item) for item in next(iter(filter_value.values())))
        self.assertTrue(valid(base["filters"]))
        self.assertTrue(valid(audit["filters"]))
        self.assertIn("note.cover", json.dumps(base))
        self.assertNotIn("canonical_status", json.dumps(base))
        self.assertIn('note.captured_at == "2026-11-01"', base["filters"]["and"])

    def old(self):
        return {"capturedAt": "previous", "captureStatus": "complete", "nodes": [
            {"id": "old-a", "url": "https://fixture.example/a", "kind": "page", "title": "A", "h1": ["A"], "wordCount": 40, "statusCode": 200, "health": "healthy", "contentHash": "old"},
            {"id": "old-b", "url": "https://fixture.example/b", "kind": "page", "title": "B", "h1": ["B"], "wordCount": 20, "statusCode": 200, "health": "healthy", "contentHash": "same"}],
            "edges": [{"source": "old-a", "target": "old-b", "kind": "internal-body"}]}

    def drift(self, nodes, **kwargs):
        return evidence_export.compute_and_write_site_drift(str(self.root), "fixture.example", "now", self.old(), nodes, [], **kwargs)

    def test_equal_length_copy_change_is_detected(self):
        nodes = [dict(node) for node in self.old()["nodes"]]
        nodes[0]["contentHash"] = "changed"
        result = self.drift(nodes)
        self.assertEqual(result["contentChangesCount"], 1)
        self.assertEqual(result["wordDeltasCount"], 0)
        self.assertTrue(result["hasChanges"])

    def test_partial_absence_never_claims_removed_page(self):
        result = self.drift(self.old()["nodes"][:1], capture_status="partial", new_edges=[])
        self.assertEqual(result["removedPagesCount"], 0)
        self.assertEqual(result["unobservedPagesCount"], 1)
        self.assertEqual(result["unobservedEdgesCount"], 1)
        self.assertFalse(result["comparisonComplete"])

    def test_fetched_404_is_recorded_separately_from_absence(self):
        node = {**self.old()["nodes"][0], "statusCode": 404, "health": "broken"}
        result = self.drift([node], capture_status="complete")
        self.assertEqual(result["confirmedMissingPagesCount"], 1)
        self.assertEqual(result["removedPagesCount"], 0)

    def test_edges_compare_url_identities_across_node_id_changes(self):
        nodes = [{**node, "id": node["id"].replace("old", "new")} for node in self.old()["nodes"]]
        result = self.drift(nodes, new_edges=[{"source": "new-a", "target": "new-b", "kind": "internal-body"}], capture_status="complete")
        self.assertEqual(result["addedEdgesCount"], 0)
        self.assertEqual(result["unobservedEdgesCount"], 0)

    def test_palette_roles_are_candidates_not_brand_assertions(self):
        brand = brand_and_dns.extract_observed_brand_kit(self.html, self.row["url"],
            source_artifacts={self.row["url"]: self.row})
        red = next(item for item in brand["palette"] if item["hex"] == "#ff0000")
        self.assertEqual(red["role"], "unassigned")
        self.assertEqual(red["confidence"], "low")
        self.assertEqual(red["rawPath"], self.row["rawPath"])
        self.assertEqual(red["quote"], "#ff0000")
        self.assertFalse(brand["visuallyInspected"])

    def pack(self, **options):
        return evidence_export.write_evidence_pack(str(self.root), "fixture.example", "fixture.example", "Claimed Brand", "https://fixture.example", "2026-11-01", {"analyticsAndPixels": [{"name": "Invented analytics"}]}, {}, {"emails": ["absent@unverified.example"]}, {}, {}, fetch_rows=[self.row], page_records=[{"url": self.row["url"], "title": "Invented Title"}], **options)

    def test_redirected_record_keeps_original_request_exclusion(self):
        self.row.update(finalUrl="https://fixture.example/final", redirectChain=[{"url": self.row["url"], "status_code": 301}])
        result = evidence_export.write_evidence_pack(str(self.root), "fixture.example", "fixture.example", "Brand", "https://fixture.example", "now", {}, {}, {}, {}, {}, fetch_rows=[self.row], page_records=[{"url": self.row["finalUrl"], "requestedUrl": self.row["url"]}])
        gap = next(row for row in result['gaps'] if row['url'] == self.row['finalUrl'])
        self.assertIn('Redirected response', gap['reason'])
        self.assertNotIn('No eligible retained page receipt', gap['reason'])
        self.assertEqual(result['observationsCount'], 0)

    def test_pack_contains_only_source_spans_and_no_invented_defaults(self):
        result = self.pack()
        output = (self.root / "_evidence-pack.md").read_text(encoding="utf-8")
        self.assertGreater(result["observationsCount"], 0)
        self.assertIn("Observed Business", output)
        self.assertNotIn("Invented Title", output)
        self.assertNotIn("Invented analytics", output)
        self.assertNotIn("absent@unverified.example", output)
        self.assertNotIn("Status: live", output)
        self.assertIn("locator `_raw/home.html:", output)
        for line in output.splitlines():
            if line.startswith("- [FETCH]"):
                quote = re.search(r': `+("(?:[^"\\]|\\.)*")`+; locator', line).group(1)
                self.assertIn(json.loads(quote), self.html)

    def test_pack_refuses_tampered_retained_source(self):
        self.path.write_bytes(b"untrusted overwrite")
        result = self.pack()
        self.assertEqual(result["observationsCount"], 0)
        self.assertTrue(result["gaps"])

    def test_blocked_stylesheet_is_not_requested(self):
        html = '<link rel="stylesheet" href="/blocked.css"><h1>Home</h1>'
        with patch("brand_and_dns.safe_requests_session", side_effect=AssertionError("network reached")):
            result = brand_and_dns.extract_observed_brand_kit(html, self.row["url"], allow_url=lambda url: False)
        self.assertTrue(result["warnings"])
        self.assertEqual(result["sources"], [])

    def test_font_provider_links_are_observed_without_api_fetches(self):
        html = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Test+Font">'
        with patch("brand_and_dns.safe_requests_session", side_effect=AssertionError("provider reached")):
            result = brand_and_dns.extract_observed_brand_kit(html, self.row["url"])
        self.assertEqual(result["typography"]["primaryFamilies"], ["Test Font"])

    def test_provider_name_is_not_invented_as_font_family(self):
        html = '<link rel="stylesheet" href="https://use.typekit.net/example.css">'
        with patch("brand_and_dns.safe_requests_session", side_effect=AssertionError("provider reached")):
            result = brand_and_dns.extract_observed_brand_kit(html, self.row["url"])
        self.assertEqual(result["typography"]["primaryFamilies"], [])
        self.assertEqual(result["faviconUrls"], [])

    def test_failed_page_does_not_invent_title_or_copy_drift(self):
        node = {**self.old()["nodes"][0], "statusCode": 503, "title": "", "h1": [], "wordCount": 0, "contentHash": "failed"}
        result = self.drift([node])
        self.assertEqual(result["titleChangesCount"], 0)
        self.assertEqual(result["h1ChangesCount"], 0)
        self.assertEqual(result["wordDeltasCount"], 0)
        self.assertEqual(result["contentChangesCount"], 0)
        self.assertEqual(result["healthChangesCount"], 1)

    def test_failed_render_with_http_200_does_not_invent_body_drift(self):
        node = {**self.old()["nodes"][0], "statusCode": 200, "health": "broken", "title": "", "h1": [], "wordCount": 0, "contentHash": ""}
        result = self.drift([node])
        self.assertEqual(result["titleChangesCount"], 0)
        self.assertEqual(result["h1ChangesCount"], 0)
        self.assertEqual(result["wordDeltasCount"], 0)
        self.assertEqual(result["contentChangesCount"], 0)
        self.assertEqual(result["healthChangesCount"], 1)

    def test_linked_css_raw_and_utf8_retention_and_redirect_policy(self):
        hits = []
        css = '/* café */ :root {--primary:#08c} .warning {color:#f00}'.encode('iso-8859-1')
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                hits.append(self.path)
                if self.path == "/redirect.css":
                    self.send_response(302)
                    self.send_header("Location", "/forbidden.css")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/css; charset=iso-8859-1")
                    self.end_headers()
                    self.wfile.write(css)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{server.server_port}"}):
                result = brand_and_dns.extract_observed_brand_kit('<link rel="stylesheet" href="/main.css"><link rel="stylesheet" href="/redirect.css">', origin,
                    allow_url=lambda url: not url.endswith("/forbidden.css"), site_root=str(self.root))
            self.assertNotIn("/forbidden.css", hits)
            self.assertEqual(len(result["sources"]), 1)
            source = result["sources"][0]
            self.assertEqual((self.root / source["rawPath"]).read_bytes(), css)
            self.assertEqual(source["rawSha256"], hashlib.sha256(css).hexdigest())
            self.assertIn("café", (self.root / source["textPath"]).read_text(encoding="utf-8"))
            self.assertEqual(source["textSha256"], hashlib.sha256((self.root / source["textPath"]).read_bytes()).hexdigest())
            self.assertTrue(all(item["rawKind"] == "decoded-text" for item in result["palette"]))
            self.assertTrue(all(item.get("rawPath") for item in result["palette"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
