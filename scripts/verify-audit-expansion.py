#!/usr/bin/env python3
"""Unit tests for per-page checks, the site audit, task persistence and field-level drift."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from audit_outputs import drift_findings, page_findings, security_txt_findings, task_id, write_tasks  # noqa: E402
from evidence_export import compute_and_write_site_drift  # noqa: E402
from extractor import extract_page_data  # noqa: E402
from issue_catalog import ISSUES, base_slug  # noqa: E402
from page_checks import keyword_density, readability, simhash64, simhash_distance  # noqa: E402
import site_audit  # noqa: E402

PROSE = " ".join(f"Web obs captures public website number {i} into Markdown notes so you can study page {i * 3} offline in Obsidian."
                 for i in range(40))


def page(body, head="", lang="en", headers=None, url="https://ex.com/page"):
    html = f"<!doctype html><html lang=\"{lang}\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">{head}</head><body>{body}</body></html>"
    return extract_page_data(html, url, "ex.com", headers or {"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "br"})


def node(url, **extra):
    base = {"url": url, "statusCode": 200, "health": "healthy", "title": "", "metaDescription": "", "h1": [], "canonical": "",
            "metaRobots": "", "flags": [], "inlinksTotal": 2, "inlinksBody": 2, "outlinksTotal": 2, "outlinksBody": 1,
            "clickDepth": 1, "contentHash": "", "simhash": "", "wordCount": 400, "inSitemap": True, "schemaTypes": [], "seoIssues": []}
    base.update(extra)
    return base


class PageCheckTests(unittest.TestCase):
    def test_document_hygiene_issues(self):
        r = page("<main><h1>Hello world page</h1><center>x</center><a href=\"http://ex.com/a\">a</a><img src=\"http://ex.com/i.png\" alt=\"i\"></main>",
                 head="<title>Hi</title><meta name=\"description\" content=\"one\"><meta name=\"description\" content=\"two\">"
                      "<meta http-equiv=\"refresh\" content=\"0; url=/x\"><script src=\"/a.js\"></script>",
                 headers={"Content-Type": "text/html; charset=iso-8859-1"})
        issues = {base_slug(i) for i in r["seo_issues"]}
        for slug in ("title-too-short", "duplicate-meta-tags", "meta-refresh-redirect", "deprecated-html-tags", "links-to-http",
                     "mixed-content", "render-blocking-resources", "charset-mismatch", "thin-content", "missing-open-graph"):
            self.assertIn(slug, issues)
        self.assertEqual(r["page_checks"]["scripts"]["renderBlocking"], ["/a.js"])
        self.assertTrue(r["page_checks"]["doctype"])

    def test_async_and_print_resources_do_not_block(self):
        r = page(f"<main><h1>Title here</h1><p>{PROSE}</p></main>", head="<title>A reasonably long page title</title>"
                 "<script async src=\"/a.js\"></script><script type=\"module\" src=\"/m.js\"></script><link rel=\"stylesheet\" href=\"/p.css\" media=\"print\">")
        self.assertNotIn("render-blocking-resources", {base_slug(i) for i in r["seo_issues"]})

    def test_every_emitted_issue_has_a_catalog_entry(self):
        r = page("<main><button></button><a href=\"/x\"></a><form><input name=q></form><img src=\"/a.png\" loading=\"lazy\"></main>", lang="")
        for issue in r["seo_issues"]:
            self.assertIn(base_slug(issue), ISSUES, issue)

    def test_accessibility_static_counts(self):
        r = page("<main><label for=\"a\">A</label><input id=\"a\"><input name=\"b\"><button aria-label=\"x\"></button><button></button>"
                 "<a href=\"/y\"><img src=\"/i.png\" alt=\"Y\"></a><a href=\"/z\"></a></main>")
        a = r["page_checks"]["accessibility"]
        self.assertEqual((a["unlabeledInputs"], a["unnamedButtons"], a["emptyLinks"]), (1, 1, 1))

    def test_dom_limits(self):
        r = page("<main><ul>" + "<li>x</li>" * 70 + "</ul></main>")
        self.assertEqual(r["page_checks"]["dom"]["maxChildren"], 70)
        self.assertIn("wide-dom-node", r["seo_issues"])

    def test_url_checks(self):
        r = page("<main><p>x</p></main>", url="https://ex.com/My_Page?id=3")
        issues = set(r["seo_issues"])
        self.assertTrue({"url-uppercase", "url-underscores", "url-has-parameters"} <= issues)
        r = page("<main><p>x</p></main>", url="https://ex.com/page?utm_source=x")
        self.assertNotIn("url-has-parameters", r["seo_issues"])

    def test_readability_and_language_gate(self):
        self.assertIsNotNone(readability(PROSE, "en"))
        self.assertIsNone(readability(PROSE, "de"))
        self.assertIsNone(readability("too short", "en"))

    def test_simhash_detects_near_duplicates(self):
        a = simhash64(PROSE + " The end.")
        b = simhash64(PROSE + " The finish.")
        c = simhash64(("Bananas grow in warm climates and ripen after harvest in dark rooms. " * 12))
        self.assertLessEqual(simhash_distance(a, b), 3)
        self.assertGreater(simhash_distance(a, c), 10)

    def test_keyword_density(self):
        kw = keyword_density(PROSE)
        self.assertIn("web obs", [row["term"] for row in kw["bigrams"]])


class SiteAuditTests(unittest.TestCase):
    def test_duplicates_exact_near_and_titles(self):
        h1 = simhash64(PROSE + " alpha")
        h2 = simhash64(PROSE + " beta")
        nodes = [node("https://ex.com/a", title="Same", contentHash="x1", simhash=h1),
                 node("https://ex.com/b", title="Same", contentHash="x2", simhash=h2),
                 node("https://ex.com/c", title="Other", contentHash="x3", simhash=simhash64("unrelated words " * 60)),
                 node("https://ex.com/d", title="Other two", contentHash="x3", wordCount=400)]
        d = site_audit.find_duplicates(nodes)
        self.assertEqual(d["titles"][0]["urls"], ["https://ex.com/a", "https://ex.com/b"])
        self.assertEqual(d["exactContent"][0]["urls"], ["https://ex.com/c", "https://ex.com/d"])
        self.assertEqual(d["nearContent"][0]["urls"], ["https://ex.com/a", "https://ex.com/b"])

    def test_noindex_pages_are_not_duplicates(self):
        nodes = [node("https://ex.com/a", title="Same"), node("https://ex.com/b", title="Same", metaRobots="noindex")]
        self.assertEqual(site_audit.find_duplicates(nodes)["titles"], [])

    def test_link_fixes(self):
        ext = {"https://ex.com/a": {"internal_links": [{"url": "https://ex.com/old", "anchor": "Old"}, {"url": "https://ex.com/gone", "anchor": "Gone"}]}}
        nodes = {"https://ex.com/new": node("https://ex.com/new"), "https://ex.com/gone": node("https://ex.com/gone", statusCode=404, health="broken")}
        rows = site_audit.internal_link_fixes(ext, nodes, {"https://ex.com/old": "https://ex.com/new"})
        self.assertEqual([(r["problem"], r["targetUrl"]) for r in rows], [("broken", "https://ex.com/gone"), ("redirect", "https://ex.com/new")])

    def test_link_opportunities_skip_linked_and_boilerplate(self):
        nodes = [node("https://ex.com/guide", h1=["Technical SEO audit"], title="Technical SEO audit | Brand"),
                 node("https://ex.com/post", title="Post"), node("https://ex.com/linked", title="Linked")]
        ext = {"https://ex.com/guide": {"visible_text": "How to run it."},
               "https://ex.com/post": {"visible_text": "We ran a technical SEO audit last week."},
               "https://ex.com/linked": {"visible_text": "Our technical SEO audit is linked."}}
        rows = site_audit.link_opportunities(nodes, ext, {("https://ex.com/linked", "https://ex.com/guide")}, "Brand")
        self.assertEqual([(r["sourceUrl"], r["targetUrl"]) for r in rows], [("https://ex.com/post", "https://ex.com/guide")])
        self.assertIn("technical SEO audit", rows[0]["context"])

    def test_signal_conflicts(self):
        nodes = [node("https://ex.com/a", canonical="https://ex.com/b"), node("https://ex.com/b", canonical="https://ex.com/a"),
                 node("https://ex.com/c", canonical="https://ex.com/d", metaRobots="noindex", inSitemap=True),
                 node("https://ex.com/d", statusCode=404, health="broken")]
        by_url = {n["url"]: n for n in nodes}
        kinds = {(r["url"], r["type"]) for r in site_audit.signal_conflicts(nodes, by_url, {}, {})}
        self.assertIn(("https://ex.com/a", "canonical-loop"), kinds)
        self.assertIn(("https://ex.com/c", "noindex-and-canonical-elsewhere"), kinds)
        self.assertIn(("https://ex.com/c", "sitemap-lists-non-canonical"), kinds)

    def test_schema_eligibility_and_mismatch(self):
        blocks = [{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "Is it free?", "acceptedAnswer": {"text": "Yes"}},
                                                      {"@type": "Question", "name": "Hidden question here", "acceptedAnswer": {"text": "No"}}]},
                  {"@type": "Product", "name": "Widget"}, {"@type": "Event", "name": "Launch"}]
        eligibility, mismatches = site_audit.schema_eligibility("https://ex.com/p", blocks, "Is it free? Yes. Widget is great.", "/p")
        by_type = {e["type"]: e for e in eligibility}
        self.assertTrue(by_type["FAQPage"]["eligible"])
        self.assertFalse(by_type["Event"]["eligible"])
        self.assertIn("startDate", by_type["Event"]["missingRequired"])
        self.assertEqual(len(mismatches), 1)

    def test_breadcrumb_user_path_is_not_a_mismatch(self):
        blocks = [{"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Shoes", "item": "https://ex.com/product-category/shoes/"}]}]
        _e, m = site_audit.schema_eligibility("https://ex.com/product/red-runner/", blocks, "", "/product/red-runner/")
        self.assertEqual(m, [])

    def test_unusual_jsonld_values_do_not_raise(self):
        blocks = [{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": ["What is X?"], "acceptedAnswer": {"text": "A"}},
                                                      {"@type": "Question", "name": 42, "acceptedAnswer": {"text": "B"}},
                                                      {"@type": "Question", "name": {"x": 1}, "acceptedAnswer": {"text": "C"}}]},
                  {"@type": "Product", "name": ["Widget"]}, {"@type": "Article", "headline": 7}]
        site_audit.schema_eligibility("https://ex.com/p", blocks, "What is X? Widget", "/p")

    def test_canonicalized_variants_are_not_duplicates(self):
        nodes = [node("https://e.com/shoes", title="Shoes", canonical="https://e.com/shoes", contentHash="h"),
                 node("https://e.com/shoes?sort=price", title="Shoes", canonical="https://e.com/shoes", contentHash="h")]
        d = site_audit.find_duplicates(nodes)
        self.assertEqual((d["titles"], d["exactContent"]), ([], []))

    def test_robots_bom_and_article_header(self):
        self.assertEqual(site_audit.robots_syntax("\ufeffUser-agent: *\nDisallow: /x\n")["issues"], [])
        r = page("<header><nav>Menu</nav></header><article><header><h1>Exact Headline Here</h1></header><p>Body text.</p></article>",
                 head="<title>Completely unrelated zebra</title>")
        self.assertIn("Exact Headline Here", r["visible_text"])
        self.assertNotIn("zebra", r["visible_text"])

    def test_robots_syntax(self):
        r = site_audit.robots_syntax("Disallow: /x\nUser-agent: *\nCrawl-delay: 5\nNoindex: /y\nFoo: bar\nSitemap: /sitemap.xml\n")
        text = " ".join(i["issue"] for i in r["issues"])
        for needle in ("before any User-agent", "Crawl-delay", "Noindex", "Unknown directive", "absolute URL"):
            self.assertIn(needle, text)

    def test_crawl_traps_and_weak_pages(self):
        ext = {"https://ex.com/": {"internal_links": [{"url": f"https://ex.com/shop?color={i}"} for i in range(12)]}}
        traps = site_audit.crawl_traps(ext)
        self.assertEqual(traps[0]["pattern"], "query-variants")
        weak = site_audit.weak_pages([node("https://ex.com/x", inlinksTotal=1, outlinksTotal=0, clickDepth=5)],
                                     {("https://ex.com/", "https://ex.com/x"): {"rels": {"nofollow"}}}, "https://ex.com/")
        self.assertEqual(weak["singleInlink"], ["https://ex.com/x"])
        self.assertEqual(weak["deadEnds"], ["https://ex.com/x"])
        self.assertEqual(weak["nofollowInternal"][0]["targetUrl"], "https://ex.com/x")

    def test_palette_contrast(self):
        self.assertEqual(site_audit.contrast_ratio("#000000", "#ffffff"), 21.0)
        table = site_audit.palette_contrast({"palette": [{"hex": "#000000"}, {"hex": "#ffffff"}, {"hex": "#777777"}]})
        self.assertEqual(len(table["colors"]), 3)
        self.assertTrue(table["pairs"][0]["aaText"])

    def test_brand_phrase_is_not_cannibalization(self):
        nodes = [node(f"https://ex.com/{i}", title=f"Acme Tool {i}", h1=[f"Acme Tool release {i}"]) for i in range(3)]
        ext = {n["url"]: {"keywords": {"bigrams": [{"term": "acme tool", "density": 5, "count": 9}]}} for n in nodes}
        self.assertEqual(site_audit.cannibalization(nodes, ext, "Acme Tool"), [])

    def test_build_site_audit_findings_have_shared_shape(self):
        nodes = [node("https://ex.com/", title="Home page title"), node("https://ex.com/a", title="Same"), node("https://ex.com/b", title="Same")]
        ext = {n["url"]: {"visible_text": PROSE, "internal_links": [], "schema_blocks": [], "keywords": {}} for n in nodes}
        audit = site_audit.build_site_audit(nodes=nodes, extracted_by_url=ext, internal_pair_meta={}, redirects={}, home_url="https://ex.com/",
                                            origin="https://ex.com", brand="Ex", resources=[], sitemaps_found=[], sitemap_urls=[],
                                            robots_text="User-agent: *\nAllow: /\n", captured_iso="2026-11-03T00:00:00Z")
        for f in audit["findings"]:
            self.assertTrue({"id", "category", "tone", "title", "explanation", "targets"} <= set(f))
        self.assertIn("dup-title", {f["id"] for f in audit["findings"]})

    def test_crawl_trap_targets_are_full_addresses(self):
        nodes = [node("https://ex.com/", title="Home page title")]
        links = [{"url": f"https://ex.com/shop?color={i}"} for i in range(12)] + [{"url": f"https://ex.com/?ref={i}"} for i in range(12)]
        links += [{"url": "https://ex.com/a/b/a/b/page"}]
        ext = {"https://ex.com/": {"visible_text": PROSE, "internal_links": links, "schema_blocks": [], "keywords": {}}}
        audit = site_audit.build_site_audit(nodes=nodes, extracted_by_url=ext, internal_pair_meta={}, redirects={}, home_url="https://ex.com/",
                                            origin="https://ex.com", brand="Ex", resources=[], sitemaps_found=[], sitemap_urls=[],
                                            robots_text="User-agent: *\nAllow: /\n", captured_iso="2026-11-03T00:00:00Z")
        traps = next(f for f in audit["findings"] if f["id"] == "crawl-traps")
        urls = [t["url"] for t in traps["targets"]]
        # A query-variants row names a path ("/shop", or "/" for the homepage); a sampled row already holds a full address.
        self.assertIn("https://ex.com/shop", urls)
        self.assertIn("https://ex.com/", urls)
        self.assertIn("https://ex.com/a/b/a/b/page", urls)
        for f in audit["findings"]:
            for t in f["targets"]:
                self.assertRegex(t["url"], r"^https?://", f"{f['id']} target is a full address")


class OutputTests(unittest.TestCase):
    def test_tasks_keep_ticks_and_close_resolved(self):
        findings = [{"id": "dup-title", "category": "content", "tone": "review", "title": "Same title",
                     "targets": [{"url": "https://ex.com/a"}, {"url": "https://ex.com/b"}]}]
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            write_tasks(old, None, findings, "2026-11-01T00:00:00Z", {"https://ex.com/a", "https://ex.com/b"}, True, {})
            text = Path(old, "_tasks.md").read_text(encoding="utf-8")
            tid = task_id("dup-title", {"url": "https://ex.com/a"})
            line = next(l for l in text.splitlines() if l.endswith(tid))
            text = text.replace(line, line.replace("- [ ]", "- [x]", 1))
            Path(old, "_tasks.md").write_text(text, encoding="utf-8")
            later = [{**findings[0], "targets": [{"url": "https://ex.com/a"}]}]
            counts = write_tasks(new, old, later, "2026-11-02T00:00:00Z", {"https://ex.com/a", "https://ex.com/b"}, True, {})
            self.assertEqual(counts, {"open": 0, "ticked": 1, "resolved": 1, "resolvedNow": 1, "notRechecked": 0})
            out = Path(new, "_tasks.md").read_text(encoding="utf-8")
            self.assertIn("(ticked, still observed)", out)
            self.assertIn("~~https://ex.com/b~~ (resolved 2026-11-02)", out)

    def test_partial_capture_does_not_resolve_unvisited_tasks(self):
        findings = [{"id": "x", "category": "content", "tone": "review", "title": "X", "targets": [{"url": "https://ex.com/z"}]}]
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            write_tasks(old, None, findings, "2026-11-01T00:00:00Z", set(), True, {})
            counts = write_tasks(new, old, [], "2026-11-02T00:00:00Z", {"https://ex.com/a"}, False, {})
            self.assertEqual(counts["notRechecked"], 1)

    def test_failed_page_and_unrun_checks_do_not_resolve_tasks(self):
        findings = [{"id": "seo:missing-h1", "category": "pages", "tone": "review", "title": "H1", "targets": [{"url": "https://ex.com/a"}]},
                    {"id": "a11y-image-alt", "category": "browser", "tone": "review", "title": "Alt", "targets": [{"url": "https://ex.com/"}]},
                    {"id": "spf-weak", "category": "security", "tone": "review", "title": "SPF", "targets": [{"url": "https://ex.com/"}]}]
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            write_tasks(old, None, findings, "2026-11-01T00:00:00Z", {"https://ex.com/", "https://ex.com/a"}, True, {})
            counts = write_tasks(new, old, [], "2026-11-02T00:00:00Z", {"https://ex.com/", "https://ex.com/a"}, True, {},
                                 ok_urls={"https://ex.com/"}, checks_ran={"browserUrls": set(), "dns": False})
            self.assertEqual((counts["resolvedNow"], counts["notRechecked"]), (0, 3))
            counts = write_tasks(tempfile.mkdtemp(), old, [], "2026-11-02T00:00:00Z", {"https://ex.com/", "https://ex.com/a"}, True, {},
                                 ok_urls={"https://ex.com/", "https://ex.com/a"}, checks_ran={"browserUrls": {"https://ex.com/"}, "dns": True})
            self.assertEqual(counts["resolvedNow"], 3)

    def test_task_ids_do_not_collide_on_one_url(self):
        f = {"id": "robots-syntax", "category": "structure", "tone": "review", "title": "Robots",
             "targets": [{"url": "https://ex.com/robots.txt", "detail": "Line 2: Unknown directive 'Foo'."},
                         {"url": "https://ex.com/robots.txt", "detail": "Line 5: Crawl-delay is ignored."}]}
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(write_tasks(d, None, [f], "2026-11-01T00:00:00Z", set(), True, {})["open"], 2)
        self.assertEqual(task_id("x", {"url": "u", "detail": "3 on this page"}), task_id("x", {"url": "u", "detail": "5 on this page"}))

    def test_change_notices_are_not_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            counts = write_tasks(d, None, [{"id": "change-title", "tone": "review", "category": "changes", "title": "T", "targets": [{"url": "u"}]}], "2026-11-01T00:00:00Z", set(), True, {})
            self.assertEqual(counts["open"], 0)

    def test_coverage_findings_are_not_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            counts = write_tasks(d, None, [{"id": "c", "tone": "coverage", "category": "links", "title": "Gap", "targets": [{"url": "u"}]}], "2026-11-01T00:00:00Z", set(), True, {})
            self.assertEqual(counts["open"], 0)

    def test_page_findings_group_issue_slugs(self):
        rows = page_findings([node("https://ex.com/a", seoIssues=["thin-content", "mixed-content (2)"])])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["seo:mixed-content"]["tone"], "attention")
        self.assertEqual(by_id["seo:mixed-content"]["targets"][0]["detail"], "2 on this page")

    def test_security_txt_expiry(self):
        from datetime import date
        rows = security_txt_findings({"validation": {"securityTxt": {"expires": "2026-11-20T00:00:00Z"}}}, "https://ex.com", date(2026, 11, 3))
        self.assertEqual(rows[0]["title"], "security.txt expires in 17 days")
        self.assertEqual(security_txt_findings({"validation": {"securityTxt": {"expires": "2027-11-20T00:00:00Z"}}}, "https://ex.com", date(2026, 11, 3)), [])

    def test_field_level_drift_and_file_diff(self):
        prev = {"schemaVersion": "1.3.0", "capturedAt": "2026-11-01T00:00:00Z", "captureStatus": "complete",
                "siteIntel": {"techStack": {"securityHeaders": {"present": ["content-security-policy"]}}},
                "nodes": [node("https://ex.com/a", canonical="https://ex.com/a", schemaTypes=["Article"], seoIssues=["thin-content"], metaDescription="old")]}
        cur = [node("https://ex.com/a", canonical="https://ex.com/b", schemaTypes=[], metaRobots="noindex", seoIssues=["mixed-content (1)"], metaDescription="new")]
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            Path(old, "llms.txt").write_text("# Ex\n> old\n", encoding="utf-8")
            Path(new, "llms.txt").write_text("# Ex\n> new\n", encoding="utf-8")
            d = compute_and_write_site_drift(new, "ex.com", "2026-11-02T00:00:00Z", prev, cur, [], capture_status="complete",
                                             previous_site_root=old, home_url="https://ex.com/", security_headers_present=[])
            self.assertEqual(d["canonicalChanges"][0]["new"], "https://ex.com/b")
            self.assertEqual(d["noindexAdded"][0]["url"], "https://ex.com/a")
            self.assertEqual(d["schemaChanges"][0]["removed"], ["Article"])
            self.assertEqual(d["issueChanges"][0]["added"], ["mixed-content"])
            self.assertEqual(d["fileChanges"][0]["file"], "llms.txt")
            self.assertEqual(d["headerChanges"]["removed"], ["content-security-policy"])
            ids = {f["id"] for f in drift_findings(d)}
            self.assertTrue({"change-noindex-added", "change-canonical", "change-schema-removed", "change-files", "change-headers"} <= ids)
            self.assertIn("File changed: llms.txt", Path(new, "_drift-report.md").read_text(encoding="utf-8"))
            legacy = compute_and_write_site_drift(new, "ex.com", "2026-11-02T00:00:00Z", {**prev, "schemaVersion": "1.2.0"}, cur, [], capture_status="complete")
            self.assertEqual(legacy["issueChanges"], [], "0.1.x captures lack the new issue types")


if __name__ == "__main__":
    unittest.main(verbosity=2)
