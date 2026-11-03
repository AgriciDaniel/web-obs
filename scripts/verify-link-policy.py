#!/usr/bin/env python3
"""Local HTTP fixtures for robots decisions, URL identity, and outbound checks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import requests
import sitemap
import site_intel
from url_safety import DEFAULT_REQUEST_HEADERS


class Fixture(BaseHTTPRequestHandler):
    hits = []
    robots_status = 200
    robots_body = "User-agent: WebObs\nDisallow: /private\n"
    denied_target = ""
    custom_routes = {}

    def log_message(self, *_args):
        pass

    def do_HEAD(self):
        self.respond(False)

    def do_GET(self):
        self.respond(True)

    def respond(self, include_body):
        self.hits.append((self.command, self.path, self.headers.get("User-Agent")))
        path = urlparse(self.path).path
        status, body, content_type, location = 200, "OK", "text/plain", None
        if path in self.custom_routes:
            status, body, content_type = self.custom_routes[path]
        elif path == "/robots.txt":
            status, body = self.robots_status, self.robots_body
        elif path == "/sitemap.xml":
            port = self.server.server_port
            content_type = "application/xml"
            body = f'<urlset><url><loc>http://127.0.0.1:{port}/public</loc></url></urlset>'
        elif path in sitemap.COMMON_SITEMAP_PATHS:
            status = 404
        elif path.startswith("/status/"):
            status = int(path.rsplit("/", 1)[1])
        elif path == "/head-unsupported" and self.command == "HEAD":
            status = 405
        elif path == "/head-501" and self.command == "HEAD":
            status = 501
        elif path.startswith('/head-result/'):
            _prefix, head_status, get_status = path.rsplit('/', 2)
            status = int(head_status if self.command == 'HEAD' else get_status)
        elif path == '/head-missing-denied-redirect':
            status = 404 if self.command == 'HEAD' else 302
            location = None if self.command == 'HEAD' else self.denied_target
        elif path == "/redirect":
            status, location = 302, "/status/410"
        elif path == "/loop":
            status, location = 302, "/loop"
        elif path == "/denied-redirect":
            status, location = 302, self.denied_target
        elif path == "/policy-redirect":
            status, location = 302, "/private/data"
        elif path == "/robots-redirect":
            status, location = 302, "/robots.txt"
        elif path == "/large":
            body = "x" * 4096
        elif path in ("/llms.txt", "/llms-full.txt"):
            body = "Published local website instructions"
        elif path.startswith("/.well-known/"):
            content_type, body = "application/json", "{}"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if include_body:
            self.wfile.write(body.encode() if isinstance(body, str) else body)


class LinkPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.env = patch.dict(os.environ, {
            "WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.server.server_port}",
            "CLAUDE_SEO_LOCAL_TARGETS": "",
        })
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    def setUp(self):
        Fixture.hits.clear()
        Fixture.robots_status = 200
        Fixture.robots_body = "User-agent: WebObs\nDisallow: /private\n"
        Fixture.custom_routes = {}
        self.tripwire = patch.object(requests.Session, "request", self.checked_request())
        self.tripwire.start()
        self.addCleanup(self.tripwire.stop)

    def checked_request(self):
        original = requests.Session.request
        expected_port = self.server.server_port
        def checked(session, method, url, *args, **kwargs):
            parsed = urlparse(url)
            self.assertEqual((parsed.hostname, parsed.port), ("127.0.0.1", expected_port), f"Unexpected destination: {url}")
            self.assertIn(method.upper(), ("HEAD", "GET"))
            self.assertFalse(session.trust_env)
            self.assertFalse(kwargs.get("allow_redirects", True), "Every hop must be checked separately")
            return original(session, method, url, *args, **kwargs)
        return checked

    def policy(self, text):
        return site_intel.build_robots_policy(text, 200)

    def decision(self, text, path):
        return site_intel.robots_url_decision(self.policy(text), self.origin + path)

    def test_webobs_named_group_overrides_wildcard_and_browser_name(self):
        text = "User-agent: *\nDisallow: /\nUser-agent: Mozilla\nDisallow: /\nUser-agent: wEbObS\nAllow: /\n"
        self.assertTrue(self.decision(text, "/public")["allowed"])
        self.assertEqual(self.policy(text)["matchedAgents"], ["webobs"])

    def test_repeated_groups_merge_and_allow_wins_equal_specificity(self):
        text = "User-agent: WebObs\nDisallow: /private\nUser-agent: WebObs\nAllow: /private/public\nDisallow: /same\nAllow: /same\n"
        self.assertFalse(self.decision(text, "/private/other")["allowed"])
        self.assertTrue(self.decision(text, "/private/public/a")["allowed"])
        self.assertTrue(self.decision(text, "/same")["allowed"])

    def test_empty_named_group_still_overrides_wildcard(self):
        self.assertTrue(self.decision("User-agent: *\nDisallow: /\nUser-agent: WebObs\n", "/")["allowed"])

    def test_unknown_fetch_states_fail_closed(self):
        for status, error, too_large in ((None, "timeout", False), (503, None, False), (429, None, False), (302, None, False), (200, None, True)):
            with self.subTest(status=status):
                policy = site_intel.build_robots_policy("", status, error, too_large)
                decision = site_intel.robots_url_decision(policy, self.origin + "/")
                self.assertEqual(decision["status"], "unknown")
                self.assertFalse(decision["allowed"])

    def test_unavailable_4xx_permitted_and_empty_success_is_distinct(self):
        for status in (401, 403, 404, 410):
            self.assertTrue(site_intel.build_robots_policy("", status)["canCrawl"])
        self.assertEqual(site_intel.build_robots_policy("", 200)["state"], "parsed")
        self.assertEqual(site_intel.build_robots_policy("", 404)["state"], "absent")

    def test_unicode_percent_encoding_query_wildcard_and_anchor(self):
        text = "\ufeffUser-agent: WebObs\nDisallow: /café\nDisallow: /a%2Fb\nDisallow: /private/*?secret=*$\nDisallow: /only$\n"
        self.assertFalse(self.decision(text, "/caf%C3%A9")["allowed"])
        self.assertFalse(self.decision(text, "/a%2fb")["allowed"])
        self.assertTrue(self.decision(text, "/a/b")["allowed"])
        self.assertFalse(self.decision(text, "/private/x?secret=yes")["allowed"])
        self.assertTrue(self.decision(text, "/only/child")["allowed"])
        self.assertFalse(self.decision("User-agent: WebObs\nDisallow: /baz", "/%62az")["allowed"])

    def test_robots_itself_implicitly_allowed(self):
        self.assertTrue(self.decision("User-agent: WebObs\nDisallow: /", "/robots.txt")["allowed"])

    def test_url_identity_keeps_reference_queries_and_ipv6(self):
        url = "https://[2606:4700:4700::1111]:8443/a;v=2?reference=1&refresh=2&ref_id=3&ref=no&utm_source=no&fbclid_extra=keep#x"
        self.assertEqual(sitemap.canonicalize_crawl_url(url), "https://[2606:4700:4700::1111]:8443/a;v=2?reference=1&refresh=2&ref_id=3&fbclid_extra=keep")
        self.assertEqual(sitemap._origin_from_target("https://[2606:4700:4700::1111]:8443/a"), "https://[2606:4700:4700::1111]:8443")
        self.assertIsNone(sitemap.canonicalize_crawl_url("https://[not-an-ip]/"))

    def test_sitemap_discovery_fetch_state_and_actual_user_agent(self):
        result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertEqual(result.robots_status_code, 200)
        self.assertEqual(result.robots_policy["productToken"], "WebObs")
        self.assertEqual(len(result.entries), 1)
        self.assertTrue(all(ua == DEFAULT_REQUEST_HEADERS["User-Agent"] for _, _, ua in Fixture.hits))

    def test_unknown_robots_fetch_stops_sitemap_requests(self):
        Fixture.robots_status = 503
        result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertFalse(result.robots_policy["canCrawl"])
        self.assertEqual([path for _, path, _ in Fixture.hits], ["/robots.txt"])

    def test_disallowed_sitemap_never_requested(self):
        Fixture.robots_body = "User-agent: WebObs\nDisallow: /*sitemap*\n"
        result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertFalse(result.entries)
        self.assertEqual([path for _, path, _ in Fixture.hits], ["/robots.txt"])

    def test_sitemap_redirect_rechecks_policy_and_byte_limit(self):
        policy = self.policy(Fixture.robots_body)
        fetched = sitemap._bounded_fetch_bytes(self.origin + "/policy-redirect", allowed_callback=lambda u: site_intel.robots_url_decision(policy, u)["allowed"])
        self.assertTrue(fetched["error"])
        self.assertNotIn("/private/data", [path for _, path, _ in Fixture.hits])
        self.assertTrue(sitemap._bounded_fetch_bytes(self.origin + "/large", max_bytes=100)["too_large"])

    def test_robots_redirect_is_followed_safely(self):
        fetched = sitemap._bounded_fetch_bytes(self.origin + "/robots-redirect")
        self.assertEqual(fetched["status_code"], 200)
        self.assertIn(b"WebObs", fetched["content"])

    def sitemap_xml(self, paths):
        return "<urlset>" + "".join(f"<url><loc>{self.origin}{path}</loc></url>" for path in paths) + "</urlset>"

    def test_declared_limit_warns_once_and_does_not_fetch_omitted_targets(self):
        Fixture.robots_body = f"User-agent: WebObs\nSitemap: {self.origin}/one.xml\nSitemap: {self.origin}/two.xml\nSitemap: {self.origin}/three.xml\n"
        Fixture.custom_routes["/one.xml"] = (200, self.sitemap_xml(["/public"]), "application/xml")
        with patch.object(sitemap, "MAX_DECLARED_SITEMAPS", 1), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ()):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(sum("Declared sitemap limit" in message for message in result.warnings), 1)
        self.assertEqual([path for _, path, _ in Fixture.hits], ["/robots.txt", "/one.xml"])

    def test_child_limit_warns_once_and_never_fetches_omitted_children(self):
        index = "<sitemapindex>" + "".join(f"<sitemap><loc>{self.origin}/{name}.xml</loc></sitemap>" for name in ("one", "one", "two", "three")) + "</sitemapindex>"
        Fixture.custom_routes["/sitemap.xml"] = (200, index, "application/xml")
        Fixture.custom_routes["/one.xml"] = (200, self.sitemap_xml(["/public"]), "application/xml")
        with patch.object(sitemap, "MAX_CHILD_SITEMAPS", 1), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ("/sitemap.xml",)):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(sum("Child sitemap limit" in message for message in result.warnings), 1)
        self.assertNotIn("/two.xml", [path for _, path, _ in Fixture.hits])
        self.assertEqual([path for _, path, _ in Fixture.hits].count("/one.xml"), 1)

    def test_exact_limits_and_duplicate_declarations_do_not_warn(self):
        Fixture.robots_body = f"User-agent: WebObs\nSitemap: {self.origin}/sitemap.xml\nSitemap: {self.origin}/sitemap.xml\n"
        index = "<sitemapindex>" + "".join(f"<sitemap><loc>{self.origin}/one.xml</loc></sitemap>" for _ in range(3)) + "</sitemapindex>"
        Fixture.custom_routes["/sitemap.xml"] = (200, index, "application/xml")
        Fixture.custom_routes["/one.xml"] = (200, self.sitemap_xml(["/public", "/public"]), "application/xml")
        with patch.object(sitemap, "MAX_DECLARED_SITEMAPS", 1), patch.object(sitemap, "MAX_CHILD_SITEMAPS", 1), patch.object(sitemap, "MAX_URLS_FROM_SITEMAPS", 1), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ()):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.warnings, [])

    def test_xml_inventory_limit_warns_once_for_unique_omissions(self):
        Fixture.custom_routes["/sitemap.xml"] = (200, self.sitemap_xml(["/public", "/public", "/second", "/third"]), "application/xml")
        with patch.object(sitemap, "MAX_URLS_FROM_SITEMAPS", 1), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ("/sitemap.xml",)):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(sum("Sitemap URL inventory limit" in message for message in result.warnings), 1)

    def test_plaintext_inventory_limit_exposes_parser_truncation(self):
        text = "\n".join(self.origin + path for path in ("/public", "/second", "/third"))
        Fixture.custom_routes["/sitemap.txt"] = (200, text, "text/plain")
        with patch.object(sitemap, "MAX_URLS_FROM_SITEMAPS", 1), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ("/sitemap.txt",)):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(sum("Sitemap URL inventory limit" in message for message in result.warnings), 1)

    def test_sitemap_byte_limit_warns_and_keeps_inventory_empty(self):
        with patch.object(sitemap, "MAX_SITEMAP_BYTES", 32), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ("/sitemap.xml",)):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertFalse(result.entries)
        self.assertEqual(sum("Sitemap response exceeded byte limit" in message for message in result.warnings), 1)

    def test_decompressed_sitemap_byte_limit_warns(self):
        payload = self.sitemap_xml(["/" + "x" * 1000])
        Fixture.custom_routes["/sitemap.xml.gz"] = (200, gzip.compress(payload.encode()), "application/gzip")
        with patch.object(sitemap, "MAX_SITEMAP_BYTES", 256), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ("/sitemap.xml.gz",)):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertFalse(result.entries)
        self.assertEqual(sum("Uncompressed sitemap exceeded byte limit" in message for message in result.warnings), 1)

    def test_robots_byte_limit_defers_crawl_with_explicit_warning(self):
        with patch.object(sitemap, "MAX_ROBOTS_BYTES", 8), patch.object(sitemap, "COMMON_SITEMAP_PATHS", ("/sitemap.xml",)):
            result = sitemap.discover_and_expand_sitemaps(self.origin)
        self.assertTrue(result.robots_too_large)
        self.assertFalse(result.robots_policy["canCrawl"])
        self.assertTrue(any("Robots response exceeded the byte limit" in message for message in result.warnings))
        self.assertEqual([path for _, path, _ in Fixture.hits], ["/robots.txt"])

    def test_discovery_endpoints_honor_robots_without_gets(self):
        with tempfile.TemporaryDirectory() as folder:
            result = site_intel.probe_ai_and_discovery_endpoints(self.origin, folder, "", robots_policy=site_intel.build_robots_policy("", 503))
        self.assertEqual(Fixture.hits, [])
        self.assertEqual(len(result["robotsSkipped"]), 13)
        self.assertTrue(all(value.startswith("unknown") for value in result["aiBotsPolicy"].values()))

    def test_discovery_endpoint_allow_exception(self):
        text = "User-agent: WebObs\nDisallow: /\nAllow: /llms.txt$\n"
        with tempfile.TemporaryDirectory() as folder:
            result = site_intel.probe_ai_and_discovery_endpoints(self.origin, folder, text, robots_policy=self.policy(text))
        self.assertEqual([path for _, path, _ in Fixture.hits], ["/llms.txt"])
        self.assertTrue(result["endpoints"]["llmsTxt"])

    def _redirecting(self, location, include_target=None):
        original = Fixture.respond
        def redirect_probe(handler, include_body):
            if handler.path == "/llms.txt":
                handler.hits.append((handler.command, handler.path, handler.headers.get("User-Agent")))
                handler.send_response(302)
                handler.send_header("Location", location)
                handler.end_headers()
            elif include_target and handler.path == include_target:
                handler.hits.append((handler.command, handler.path, handler.headers.get("User-Agent")))
                body = b"# Site\n\n> Summary\n\n## Docs\n- [Home](https://example.test/)\n"
                handler.send_response(200)
                handler.send_header("Content-Type", "text/plain; charset=utf-8")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
            else:
                original(handler, include_body)
        return patch.object(Fixture, "respond", redirect_probe)

    def test_discovery_redirect_to_robots_blocked_path_is_not_fetched(self):
        with self._redirecting("/private/probe"), tempfile.TemporaryDirectory() as folder:
            result = site_intel.probe_ai_and_discovery_endpoints(self.origin, folder, Fixture.robots_body)
        self.assertNotIn("/private/probe", [path for _, path, _ in Fixture.hits])
        self.assertFalse(result["endpoints"]["llmsTxt"])
        self.assertTrue(any(row["url"].endswith("/private/probe") for row in result["robotsSkipped"]))

    def test_same_origin_discovery_redirect_is_followed_and_validated(self):
        with self._redirecting("/docs/llms-real.txt", "/docs/llms-real.txt"), tempfile.TemporaryDirectory() as folder:
            result = site_intel.probe_ai_and_discovery_endpoints(self.origin, folder, Fixture.robots_body)
        self.assertTrue(result["endpoints"]["llmsTxt"])
        self.assertTrue(result["validation"]["llmsTxt"]["valid"])

    def test_cross_origin_discovery_redirect_is_recorded_not_followed(self):
        with self._redirecting("http://other.invalid/llms.txt"), tempfile.TemporaryDirectory() as folder:
            result = site_intel.probe_ai_and_discovery_endpoints(self.origin, folder, Fixture.robots_body)
        self.assertFalse(result["endpoints"]["llmsTxt"])
        self.assertTrue(any(row.get("redirectedTo") == "http://other.invalid/llms.txt" for row in result["robotsSkipped"]))

    def test_llms_txt_validation_follows_spec(self):
        self.assertTrue(site_intel.validate_llms_txt("# Name\n\n> Sum\n\n## A\n- [x](https://a.test/)\n")["valid"])
        bad = site_intel.validate_llms_txt("Welcome\nno heading")
        self.assertFalse(bad["valid"])
        self.assertIn("missing-h1-title", bad["issues"])
        self.assertIn("no-link-list", bad["issues"])

    def test_security_txt_requires_contact_and_future_expires(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        good = site_intel.validate_security_txt("Contact: mailto:a@b.test\nExpires: 2027-01-01T00:00:00Z\n", now)
        self.assertTrue(good["valid"])
        self.assertTrue(site_intel.validate_security_txt("Contact: x\nExpires: 2027-01-01t00:00:00z", now)["valid"])
        expired = site_intel.validate_security_txt("Contact: mailto:a@b.test\nExpires: 2025-01-01T00:00:00Z\n", now)
        self.assertIn("expired", expired["issues"])
        missing = site_intel.validate_security_txt("Contact: mailto:a@b.test\n", now)
        self.assertIn("missing-expires", missing["issues"])
        self.assertIn("missing-contact", site_intel.validate_security_txt("Expires: 2027-01-01T00:00:00Z", now)["issues"])
        self.assertIn("invalid-expires", site_intel.validate_security_txt("Contact: x\nExpires: soon", now)["issues"])

    def test_ai_bot_list_includes_documented_user_agents(self):
        tokens = {name for name, _ in site_intel.AI_BOT_TOKENS}
        for name in ("Claude-User", "ClaudeBot", "Claude-SearchBot", "OAI-AdsBot", "Perplexity-User", "meta-externalagent"):
            self.assertIn(name, tokens)
        result = site_intel.parse_robots_ai_policy("User-agent: Claude-User\nDisallow: /\n")
        self.assertTrue(result["Claude-User"].startswith("blocked"))
        self.assertTrue(result["ClaudeBot"].startswith("allowed"))

    def test_same_site_allows_www_and_https_but_not_other_sites(self):
        self.assertTrue(site_intel._same_site("https://a.test/x", "https://www.a.test/x"))
        self.assertTrue(site_intel._same_site("http://a.test/", "https://a.test/"))
        self.assertFalse(site_intel._same_site("https://a.test/", "https://b.test/"))

    def test_robots_analysis_flags_blanket_disallow_and_blocked_assets(self):
        found = site_intel.analyze_robots("User-agent: *\nDisallow: /\n")
        self.assertTrue(found["blanketDisallow"])
        self.assertFalse(found["hasSitemapLine"])
        found = site_intel.analyze_robots("User-agent: *\nDisallow: /wp-includes/\nDisallow: /*.js$\nContent-Signal: ai-train=no\nSitemap: https://a.test/s.xml\n")
        self.assertFalse(found["blanketDisallow"])
        self.assertEqual(len(found["blocksAssets"]), 2)
        self.assertTrue(found["hasSitemapLine"])
        self.assertEqual(found["contentSignal"], "ai-train=no")

    def test_soft_404_probe_reports_real_404(self):
        with tempfile.TemporaryDirectory() as folder:
            result = site_intel.probe_ai_and_discovery_endpoints(self.origin, folder, Fixture.robots_body)
        self.assertIn(result["siteChecks"]["soft404"]["state"], ("ok", "fail", "warn"))
        self.assertIn("statusCode", result["siteChecks"]["soft404"])

    def test_page_level_seo_flags(self):
        import extractor
        html = "<html lang='en'><head><title>T</title><meta name='robots' content='nofollow'><link rel='alternate' hreflang='fr' href='https://a.test/fr'><script type='application/ld+json'>{bad json</script></head><body><h1>H</h1></body></html>"
        issues = extractor.extract_page_data(html, "https://a.test/", "a.test")["seo_issues"]
        for expected in ("nofollow", "missing-viewport", "hreflang-missing-self"):
            self.assertIn(expected, issues)
        self.assertTrue(any(i.startswith("invalid-jsonld") for i in issues))
        ok = "<html><head><title>T</title><meta name='viewport' content='width=device-width'></head><body><h1>H</h1></body></html>"
        clean = extractor.extract_page_data(ok, "https://a.test/", "a.test")["seo_issues"]
        self.assertNotIn("missing-viewport", clean)
        self.assertNotIn("nofollow", clean)

    def test_encoded_literal_special_characters_match_without_decoding_slashes(self):
        text = "User-agent: WebObs\nDisallow: /file%2A\nDisallow: /price%24\n"
        self.assertFalse(self.decision(text, "/file*")["allowed"])
        self.assertFalse(self.decision(text, "/price$")["allowed"])
        self.assertTrue(self.decision(text, "/file-other")["allowed"])

    def test_http_status_categories_keep_5xx_and_access_limits_separate(self):
        statuses = [200, 404, 410, 500, 503, 403, 429, 401]
        result = site_intel.check_external_links([self.origin + f"/status/{s}" for s in statuses])
        self.assertEqual([row["status"] for row in result["results"]], ["ok", "broken", "broken", "server-error", "server-error", "unknown", "unknown", "unknown"])
        self.assertEqual(len(result["brokenLinks"]), 2)
        self.assertEqual(result["unknownCount"], 3)
        self.assertEqual(result["checkedCount"], 8)
        self.assertFalse(result["coverageComplete"])

    def test_all_targets_checked_without_two_per_domain_sampling(self):
        urls = [self.origin + f"/page/{n}" for n in range(6)]
        result = site_intel.check_external_links(urls + [urls[0] + "#fragment"])
        self.assertEqual(result["totalCount"], 6)
        self.assertEqual(result["checkedCount"], 6)
        self.assertTrue(result["coverageComplete"])

    def test_head_fallback_and_validated_redirect(self):
        result = site_intel.check_external_links([self.origin + "/head-unsupported", self.origin + "/head-501", self.origin + "/redirect"])
        self.assertEqual([row["status"] for row in result["results"]], ["ok", "ok", "broken"])
        self.assertEqual([row["method"] for row in result["results"]], ["GET", "GET", "GET"])
        self.assertEqual(result["results"][2]["finalUrl"], self.origin + "/status/410")

    def test_head_missing_statuses_require_streamed_get_confirmation(self):
        cases = [(404, 200, 'ok'), (410, 200, 'ok'), (404, 404, 'broken'), (404, 403, 'unknown')]
        for head_status, get_status, expected in cases:
            with self.subTest(head=head_status, get=get_status):
                Fixture.hits.clear()
                url = self.origin + f'/head-result/{head_status}/{get_status}'
                with patch.object(requests.Response, 'iter_content', side_effect=AssertionError('Link checker must not consume a response body')):
                    result = site_intel._check_direct_external_url(url, time.monotonic() + 5, 2)
                self.assertEqual((result['status'], result['statusCode'], result['method']), (expected, get_status, 'GET'))
                self.assertEqual(result['headStatusCode'], head_status)
                self.assertEqual([(method, path) for method, path, _ua in Fixture.hits],
                                 [('HEAD', urlparse(url).path), ('GET', urlparse(url).path)])

    def test_get_confirmation_timeout_keeps_preliminary_head_out_of_final_status(self):
        original = requests.Session.request
        def fail_get(session, method, url, *args, **kwargs):
            if method.upper() == 'GET':
                raise requests.Timeout('Synthetic GET confirmation timeout')
            return original(session, method, url, *args, **kwargs)
        with patch.object(requests.Session, 'request', fail_get):
            result = site_intel._check_direct_external_url(self.origin + '/head-result/404/200', time.monotonic() + 5, 2)
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['statusCode'])
        self.assertEqual((result['headStatusCode'], result['method']), (404, 'GET'))

    def test_head_missing_confirmation_cannot_reset_the_shared_time_budget(self):
        with patch.object(site_intel, 'time') as clock:
            clock.monotonic.side_effect = [0, 6]
            result = site_intel._check_direct_external_url(self.origin + '/head-result/404/200', 5, 2)
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['statusCode'])
        self.assertEqual((result['headStatusCode'], result['method']), (404, 'GET'))
        self.assertIn('time budget', result['reason'])
        self.assertEqual([method for method, _path, _ua in Fixture.hits], ['HEAD'])

    def test_count_budget_retains_unchecked_targets_and_zero_budget_requests_none(self):
        urls = [self.origin + f"/page/{n}" for n in range(5)]
        result = site_intel.check_external_links(urls, max_checks=2)
        self.assertEqual((result["totalCount"], result["checkedCount"], result["uncheckedCount"]), (5, 2, 3))
        self.assertFalse(result["allAttempted"])
        Fixture.hits.clear()
        result = site_intel.check_external_links(urls, max_checks=0)
        self.assertEqual(Fixture.hits, [])
        self.assertEqual(result["uncheckedCount"], 5)

    def test_time_budget_and_invalid_urls_remain_explicit(self):
        result = site_intel.check_external_links([self.origin, "mailto:a@example.com"], max_seconds=0)
        self.assertEqual(result["uncheckedCount"], 2)
        self.assertEqual(Fixture.hits, [])
        self.assertTrue(all(row["reason"] for row in result["results"]))

    def test_network_failure_and_loop_are_unknown_not_broken(self):
        with patch("site_intel.safe_requests_session", side_effect=requests.ConnectionError("local fixture failure")):
            failed = site_intel.check_external_links([self.origin])
        self.assertEqual(failed["unknownCount"], 1)
        self.assertEqual(failed["brokenLinks"], [])
        loop = site_intel.check_external_links([self.origin + "/loop"])
        self.assertEqual(loop["unknownCount"], 1)
        self.assertEqual(loop["results"][0]["reason"], "Redirect loop.")

    def test_redirect_denied_before_second_server_is_contacted(self):
        denied_hits = []
        class Denied(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_HEAD(self):
                denied_hits.append(self.path)
                self.send_response(200)
                self.end_headers()
        denied = ThreadingHTTPServer(("127.0.0.1", 0), Denied)
        worker = threading.Thread(target=denied.serve_forever, daemon=True)
        worker.start()
        Fixture.denied_target = f"http://127.0.0.1:{denied.server_port}/private"
        try:
            for path in ('/denied-redirect', '/head-missing-denied-redirect'):
                with self.subTest(path=path):
                    result = site_intel.check_external_links([self.origin + path])
                    self.assertEqual(denied_hits, [])
                    self.assertEqual(result["unknownCount"], 1)
                    self.assertIn("URL safety", result["results"][0]["reason"])
        finally:
            denied.shutdown()
            denied.server_close()
            worker.join(timeout=2)


class HeaderConsistencyTests(unittest.TestCase):
    FULL = {
        "Strict-Transport-Security": "max-age=31536000", "Content-Security-Policy": "default-src 'self'",
        "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=()",
    }

    def test_all_pages_consistent(self):
        result = site_intel.summarize_header_consistency({"https://a/": self.FULL, "https://a/x": dict(self.FULL)})
        self.assertEqual(result["inconsistent"], [])
        self.assertEqual(result["sampledPages"], 2)
        self.assertTrue(all(row["state"] == "all" for row in result["headers"]))

    def test_header_missing_on_inner_page_is_inconsistent(self):
        inner = {k: v for k, v in self.FULL.items() if k != "Content-Security-Policy"}
        result = site_intel.summarize_header_consistency({"https://a/": self.FULL, "https://a/blog": inner})
        self.assertEqual(result["inconsistent"], ["CSP"])
        csp = next(row for row in result["headers"] if row["header"] == "CSP")
        self.assertEqual((csp["presentOn"], csp["of"], csp["missingOn"]), (1, 2, ["https://a/blog"]))

    def test_header_absent_everywhere_is_none_not_inconsistent(self):
        bare = {k: v for k, v in self.FULL.items() if k != "Permissions-Policy"}
        result = site_intel.summarize_header_consistency({"https://a/": bare, "https://a/x": bare})
        self.assertEqual(result["inconsistent"], [])
        self.assertEqual(next(row for row in result["headers"] if row["header"] == "Permissions-Policy")["state"], "none")

    def test_header_names_are_case_insensitive_and_blank_values_count_as_missing(self):
        result = site_intel.summarize_header_consistency({"https://a/": {"x-frame-options": "DENY"}, "https://a/x": {"X-Frame-Options": "  "}})
        self.assertEqual(result["inconsistent"], ["X-Frame-Options"])

    def test_weak_hsts_is_noted(self):
        weak = dict(self.FULL, **{"Strict-Transport-Security": "max-age=300"})
        result = site_intel.summarize_header_consistency({"https://a/": weak})
        self.assertEqual(len(result["notes"]), 1)
        self.assertIn("max-age is 300", result["notes"][0])
        self.assertEqual(site_intel.summarize_header_consistency({"https://a/": self.FULL})["notes"], [])
        self.assertEqual(site_intel.hsts_max_age('max-age="63072000"; includeSubDomains'), 63072000)
        self.assertIsNone(site_intel.hsts_max_age("includeSubDomains"))

    def test_empty_sample_is_safe(self):
        result = site_intel.summarize_header_consistency({})
        self.assertEqual((result["sampledPages"], result["inconsistent"]), (0, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
