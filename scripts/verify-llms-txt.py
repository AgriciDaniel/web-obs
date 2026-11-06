"""llms.txt: the llmstxt.org format rules, links checked against the capture, findings and tasks,
and the draft built from captured pages.

Offline: the fixture site is served on 127.0.0.1 and allowed through WEB_OBS_LOCAL_TARGETS.
"""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(ENGINE))
import audit_outputs  # noqa: E402
import crawl_site  # noqa: E402
import llms_txt  # noqa: E402
import site_intel  # noqa: E402

# The example file published on llmstxt.org.
SPEC_EXAMPLE = """# FastHTML

> FastHTML is a python library which brings together Starlette, Uvicorn, HTMX, and fastcore's `FT` "FastTags" into a library for creating server-rendered hypermedia applications.

Important notes:

- Although parts of its API are inspired by FastAPI, it is *not* compatible with FastAPI syntax and is not targeted at creating API services
- FastHTML is compatible with JS-native web components and any vanilla JS library, but not with React, Vue, or Svelte.

## Docs

- [FastHTML quick start](https://fastht.ml/docs/tutorials/quickstart_for_web_devs.html.md): A brief overview of many FastHTML features
- [HTMX reference](https://raw.githubusercontent.com/path/reference.md): Brief description of all HTMX attributes, CSS classes, headers, events, extensions, js lib methods, and config options

## Examples

- [Todo list application](https://raw.githubusercontent.com/path/adv_app.py): Detailed walk-thru of a complete CRUD app in FastHTML showing idiomatic use of FastHTML and HTMX patterns.

## Optional

- [Starlette full documentation](https://gist.githubusercontent.com/path/starlette-sml.md): A subset of the Starlette documentation useful for FastHTML development.
"""


def codes(text, **kwargs):
    return [n["code"] for n in llms_txt.validate_llms_txt(text, **kwargs)["notes"]]


class Format(unittest.TestCase):
    def test_the_spec_example_has_no_notes(self):
        result = llms_txt.validate_llms_txt(SPEC_EXAMPLE, base_url="https://fastht.ml/llms.txt", content_type="text/plain; charset=utf-8")
        self.assertTrue(result["valid"])
        self.assertEqual(result["notes"], [])
        self.assertEqual(result["title"], "FastHTML")
        self.assertTrue(result["summary"].startswith("FastHTML is a python library"))
        self.assertEqual([s["name"] for s in result["sections"]], ["Docs", "Examples", "Optional"])
        self.assertTrue(result["hasOptional"])
        self.assertEqual(result["stats"]["links"], 4)
        self.assertEqual(result["stats"]["markdownLinks"], 3)

    def test_only_the_title_is_required(self):
        result = llms_txt.validate_llms_txt("# Just a name\n")
        self.assertTrue(result["valid"])
        self.assertEqual(result["issues"], ["no-summary-blockquote", "no-link-list"])
        self.assertEqual({n["level"] for n in result["notes"]}, {"warn", "info"})

    def test_a_byte_order_mark_is_allowed(self):
        self.assertTrue(llms_txt.validate_llms_txt("﻿# Name\n\n> Summary.\n")["valid"])

    def test_the_title_must_come_first_and_only_once(self):
        result = llms_txt.validate_llms_txt("Welcome\n# Name\n")
        self.assertFalse(result["valid"])
        self.assertEqual(result["notes"][0]["code"], "missing-h1-title")
        self.assertIn("multiple-h1", codes("# One\n\n> S\n\n# Two\n"))
        self.assertFalse(llms_txt.validate_llms_txt("# One\n\n> S\n\n# Two\n")["valid"])

    def test_summary_position(self):
        self.assertIn("summary-not-after-title", codes("# Name\n\nText first.\n\n> Late summary.\n"))
        self.assertNotIn("summary-not-after-title", codes("# Name\n> Right after.\n> Second line.\n"))

    def test_only_h2_may_split_the_file(self):
        notes = llms_txt.validate_llms_txt("# Name\n\n> S\n\n### Details\n\nText.\n\n## Docs\n- [A](https://a.test/): a\n")["notes"]
        self.assertEqual([(n["code"], n["line"]) for n in notes], [("heading-in-details", 5)])

    def test_headings_inside_code_blocks_are_ignored(self):
        self.assertEqual(codes("# Name\n\n> S\n\n```\n# not a title\n### nor this\n```\n\n## Docs\n- [A](https://a.test/): a\n"), [])

    def test_file_list_items(self):
        text = ("# Name\n\n> S\n\n## Docs\n"
                "* [Star](https://a.test/1): starred\n"
                "- [No colon](https://a.test/2) the notes\n"
                "- See [late link](https://a.test/3)\n"
                "- just words\n"
                "- [Spaced] (https://a.test/4)\n"
                "- Docs: https://a.test/5\n"
                "- [Mail](mailto:a@a.test)\n"
                "- [Again](https://a.test/1): repeat\n")
        # lines: 6 star, 7 no colon, 8 sentence link, 9 words, 10 spaced, 11 bare address, 12 mailto, 13 repeat
        notes = {(n["code"], n["line"]) for n in llms_txt.validate_llms_txt(text)["notes"]}
        self.assertTrue({("bullet-not-dash", 6), ("notes-without-colon", 7), ("link-not-at-start", 8),
                         ("item-without-link", 9), ("malformed-link", 10), ("malformed-link", 11), ("invalid-url", 12),
                         ("duplicate-link", 13)} <= notes, notes)
        levels = {n["code"]: n["level"] for n in llms_txt.validate_llms_txt(text)["notes"]}
        self.assertEqual(levels["malformed-link"], "warn", "a link that cannot be followed is a problem")
        self.assertEqual(levels["item-without-link"], "info", "a plain note in a list is guidance only")
        self.assertEqual(levels["link-not-at-start"], "info")

    def test_long_files_show_five_of_each_note_and_count_the_rest(self):
        text = "# Name\n\n> S\n\n## Docs\n" + "".join(f"- [P{i}](https://a.test/{i}) - dash notes\n" for i in range(40))
        result = llms_txt.validate_llms_txt(text)
        shown = [n for n in result["notes"] if n["code"] == "notes-without-colon"]
        self.assertEqual(len(shown), 5)
        self.assertEqual(result["noteCounts"]["notes-without-colon"], 40)
        self.assertIn("35 more lines like this", shown[-1]["message"])

    def test_relative_links_resolve_against_the_file(self):
        result = llms_txt.validate_llms_txt("# Name\n\n> S\n\n## Docs\n- [About](/about): about\n", base_url="https://brand.test/llms.txt")
        self.assertEqual(result["links"][0]["url"], "https://brand.test/about")
        self.assertTrue(result["links"][0]["sameSite"])
        self.assertEqual([n["level"] for n in result["notes"]], ["info"])

    def test_sections_optional_and_guidance(self):
        self.assertIn("empty-section", codes("# Name\n\n> S\n\n## Empty\n\n## Docs\n- [A](https://a.test/): a\n"))
        self.assertIn("optional-heading-variant", codes("# Name\n\n> S\n\n## optional links\n- [A](https://a.test/): a\n"))
        self.assertNotIn("optional-heading-variant", codes(SPEC_EXAMPLE))
        self.assertIn("links-without-notes", codes("# Name\n\n> S\n\n## Docs\n- [A](https://a.test/a)\n- [B](https://a.test/b)\n"))
        self.assertIn("oversize", codes("# Name\n\n> S\n\n" + ("Words. " * 20000)))
        self.assertIn("content-type", codes("# Name\n\n> S\n", content_type="application/octet-stream"))
        self.assertNotIn("content-type", codes("# Name\n\n> S\n", content_type="text/markdown; charset=utf-8"))

    def test_names_with_a_hash_keep_it(self):
        self.assertEqual(llms_txt.validate_llms_txt("# C#\n\n> S\n")["title"], "C#")
        self.assertEqual(llms_txt.validate_llms_txt("# Name ##\n\n> S\n")["title"], "Name", "a spaced closing sequence is dropped")

    def test_link_destinations_markdown_allows(self):
        text = ("# Name\n\n> S\n\n## Docs\n"
                "- [Wiki](https://en.wikipedia.org/wiki/Foo_(bar)): note\n"
                "- [Angle](<https://a.test/y>): angle\n")
        result = llms_txt.validate_llms_txt(text, base_url="https://a.test/llms.txt")
        self.assertEqual([link["url"] for link in result["links"]], ["https://en.wikipedia.org/wiki/Foo_(bar)", "https://a.test/y"])
        self.assertEqual(result["notes"], [])

    def test_numbered_items_and_fences(self):
        result = llms_txt.validate_llms_txt("# Name\n\n> S\n\n## Docs\n1. [One](https://a.test/1): one\n"
                                            "```\n~~~\n## inside a code block\n```\n")
        self.assertEqual([(n["code"], n["line"]) for n in result["notes"]], [("bullet-not-dash", 6)])
        self.assertEqual([s["name"] for s in result["sections"]], ["Docs"], "a ~~~ inside a ``` block does not end it")

    def test_a_relative_link_without_a_base_still_counts(self):
        self.assertNotIn("empty-section", codes("# Name\n\n> S\n\n## Docs\n- [About](/about): about\n"))

    def test_site_intel_keeps_its_entry_point(self):
        self.assertTrue(site_intel.validate_llms_txt("# Name\n\n> Sum\n\n## A\n- [x](https://a.test/): x\n")["valid"])

    def test_llms_full_is_a_convention(self):
        result = llms_txt.validate_llms_full_txt("# Everything\n\nAll the text.")
        self.assertTrue(result["convention"])
        self.assertEqual(result["issues"], [])


class Draft(unittest.TestCase):
    def node(self, path, **extra):
        url = "https://brand.test" + path
        base = {"kind": "page", "url": url, "path": path, "title": path.strip("/").title() or "Home", "statusCode": 200,
                "metaDescription": f"About {path}.", "canonical": url, "metaRobots": "", "redirectChain": [],
                "section": "root" if path == "/" else path.strip("/").split("/")[0], "urlDepth": len([p for p in path.split("/") if p]),
                "authorityScore": 1}
        return {**base, **extra}

    def test_draft_is_valid_and_built_only_from_good_pages(self):
        nodes = [self.node("/", authorityScore=9, metaDescription="Brand makes things for [teams]."),
                 self.node("/about", authorityScore=5),
                 self.node("/blog", authorityScore=4), self.node("/blog/one", authorityScore=3), self.node("/blog/two", authorityScore=2),
                 self.node("/hidden", metaRobots="noindex"),
                 self.node("/moved", redirectChain=[{"statusCode": 301}]),
                 self.node("/copy", canonical="https://brand.test/about"),
                 self.node("/gone", statusCode=404)]
        draft = llms_txt.draft_llms_txt("Brand", "https://brand.test/", nodes, {"https://brand.test/about": ["https://brand.test/about.md"]})
        result = llms_txt.validate_llms_txt(draft["text"], base_url="https://brand.test/llms.txt")
        self.assertTrue(result["valid"])
        self.assertEqual([n for n in result["notes"] if n["level"] != "info"], [], draft["text"])
        self.assertEqual(result["title"], "Brand")
        self.assertEqual(result["summary"], "Brand makes things for (teams).", "brackets cannot break the markdown")
        self.assertIn("- [About](https://brand.test/about.md): About /about.", draft["text"], "a declared markdown version is linked")
        self.assertIn("## Blog", draft["text"])
        self.assertNotIn("## About", draft["text"], "a lone top-level page is a main page")
        for left_out in ("/hidden", "/moved", "/copy", "/gone"):
            self.assertNotIn(f"brand.test{left_out})", draft["text"])

    def test_draft_reads_like_the_site_wrote_it(self):
        nodes = [self.node("/", authorityScore=9, title="Brand | Home of things", metaDescription="Brand makes things."),
                 self.node("/pricing", authorityScore=8, title="Pricing | Brand"),
                 self.node("/privacy-policy", authorityScore=7, title="Privacy Policy | Brand"),
                 self.node("/blog", authorityScore=6), self.node("/blog/terms-explained", authorityScore=5, title="Terms explained")]
        text = llms_txt.draft_llms_txt("Brand", "https://brand.test/", nodes)["text"]
        self.assertIn("- [Pricing](https://brand.test/pricing)", text, "the brand suffix is dropped from titles")
        self.assertIn("- [Home of things](https://brand.test/)\n", text, "the home link does not repeat the summary")
        main, _, optional = text.partition("## Optional")
        self.assertIn("privacy-policy", optional, "policy pages are secondary")
        self.assertNotIn("privacy-policy", main)
        self.assertIn("terms-explained", main, "a blog post about terms is not a policy page")

    def test_draft_without_a_home_description_has_no_invented_summary(self):
        draft = llms_txt.draft_llms_txt("Brand", "https://brand.test/", [self.node("/", metaDescription="")])
        self.assertFalse(draft["hasSummary"])
        self.assertNotIn(">", draft["text"])

    def test_long_sites_fold_into_optional(self):
        nodes = [self.node("/")] + [self.node(f"/docs/p{i}", authorityScore=100 - i) for i in range(90)]
        draft = llms_txt.draft_llms_txt("Brand", "https://brand.test/", nodes)
        result = llms_txt.validate_llms_txt(draft["text"])
        self.assertTrue(result["hasOptional"])
        self.assertLessEqual(next(s["links"] for s in result["sections"] if s["name"] == "Docs"), llms_txt.DRAFT_SECTION_LINKS)


class Fixture(BaseHTTPRequestHandler):
    llms_mode = "file"

    def do_GET(self):
        host = f"http://127.0.0.1:{self.server.server_port}"
        path = self.path.split("?", 1)[0]
        page = lambda title, body, head="": (f"<!doctype html><html lang=en><head><title>{title}</title>"
                                             f"<meta name=description content='{title} for the fixture.'>{head}</head>"
                                             f"<body><main><h1>{title}</h1><p>{'Plenty of words here. ' * 30}</p>{body}</main></body></html>")
        if path == "/robots.txt":
            return self.reply("User-agent: *\nDisallow: /private\n\nUser-agent: ChatGPT-User\nDisallow: /\n", "text/plain")
        if path == "/sitemap.xml":
            urls = "".join(f"<url><loc>{host}{p}</loc></url>" for p in ("/", "/about", "/blog", "/blog/one", "/blog/two", "/old"))
            return self.reply(f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', "application/xml")
        if path == "/llms.txt":
            if Fixture.llms_mode == "missing":
                return self.reply("", "text/plain", 404)
            if Fixture.llms_mode == "html":
                return self.reply(page("Home", ""), "text/html; charset=utf-8")
            if Fixture.llms_mode == "error":
                return self.reply("Server error", "text/plain", 503)
            return self.reply("# Fixture Co\n\n> We make fixtures.\n\n## Main\n\n"
                              "- [Home](/): the home page\n"
                              f"- [About]({host}/about): about us\n"
                              f"- [Gone]({host}/gone): a missing page\n"
                              f"- [Old]({host}/old): moved\n"
                              f"- [Secret]({host}/private/x): blocked\n"
                              f"- [Unlisted]({host}/unlisted-page): reached only through llms.txt\n"
                              "- [Elsewhere](https://example.org/x): another site\n"
                              f"* [Star]({host}/blog): starred bullet\n", "text/markdown; charset=utf-8")
        if path == "/":
            return self.reply(page("Home", "<a href='/about'>About</a> <a href='/blog'>Blog</a>"), "text/html; charset=utf-8")
        if path == "/about":
            return self.reply(page("About", "<a href='/'>Home</a>", "<link rel='alternate' type='text/markdown' href='/about.md'>"
                                                                 "<link rel='describedby' href='/llms.txt'>"), "text/html; charset=utf-8")
        if path == "/about.md":
            return self.reply("# About\n\nAbout us, in markdown.\n", "text/markdown; charset=utf-8")
        if path == "/blog":  # the v2 pointer sent as an HTTP Link header; its copy is really an HTML page
            return self.reply(page("Blog", "<a href='/blog/one'>One</a> <a href='/blog/two'>Two</a>"), "text/html; charset=utf-8",
                              headers={"Link": '</blog.md>; rel="alternate"; type="text/markdown"'})
        if path == "/blog.md":
            return self.reply(page("Blog", ""), "text/html; charset=utf-8")
        if path == "/blog/one":
            return self.reply(page("Post one", "<a href='/blog'>Blog</a>", "<link rel='alternate' type='text/markdown' href='/blog/one.md'>"),
                              "text/html; charset=utf-8")
        if path == "/blog/two":
            return self.reply(page("Post two", "<a href='/blog'>Blog</a>", "<meta name=robots content=noindex>"), "text/html; charset=utf-8")
        if path == "/unlisted-page":
            return self.reply(page("Unlisted", ""), "text/html; charset=utf-8")
        if path == "/old":
            self.send_response(301)
            self.send_header("Location", f"{host}/about")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        return self.reply("Not here", "text/plain", 404)

    def reply(self, body, kind, status=200, headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class Capture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.server.server_port}", "CLAUDE_SEO_LOCAL_TARGETS": ""})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def capture(self, directory, mode):
        Fixture.llms_mode = mode
        with redirect_stdout(io.StringIO()):
            manifest = crawl_site.crawl_website_to_vault(self.origin, directory, max_pages=20, render_mode="never", download_images=False,
                                                         delay_sec=0, check_external=False, parallel=False, browser_audit=False,
                                                         snapshot_limit=0, dns_checks=False, tls_check=False)
        return manifest, Path(directory) / "sites" / manifest["siteId"]

    def test_links_are_checked_against_the_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, site = self.capture(directory, "file")
            ai = manifest["siteIntel"]["aiReadiness"]
            self.assertEqual(ai["llmsProbe"]["llmsTxt"]["state"], "found")
            states = {row["url"].removeprefix(self.origin): row["state"] for row in ai["llmsLinks"]}
            self.assertEqual(states, {"/": "ok", "/about": "ok", "/gone": "broken", "/old": "redirect", "/private/x": "blocked",
                                      "/unlisted-page": "ok", "https://example.org/x": "external", "/blog": "ok"})
            findings = {f["id"]: f for f in manifest["audit"]["findings"]}
            dead = {t["url"].removeprefix(self.origin) for t in findings["llmstxt-dead-links"]["targets"]}
            self.assertEqual(dead, {"/gone", "/private/x"})
            self.assertEqual(findings["llmstxt-dead-links"]["tone"], "attention")
            self.assertEqual({t["url"].removeprefix(self.origin) for t in findings["llmstxt-link-hygiene"]["targets"]}, {"/old"})
            self.assertTrue(any("reference parser reads only" in t["detail"] for t in findings["llmstxt-format"]["targets"]))
            self.assertIn("llmstxt-agents-blocked", findings, "ChatGPT-User is blocked while llms.txt is offered")
            self.assertEqual(ai["describedBy"], [f"{self.origin}/llms.txt"])
            self.assertEqual(ai["markdownAlternatePages"], 3, "two <link> tags and one HTTP Link header")
            copies = {r["url"].removeprefix(self.origin): r["state"] for r in ai["markdownAlternates"]["checked"]}
            self.assertEqual(copies, {"/about.md": "ok", "/blog.md": "html", "/blog/one.md": "broken"})
            broken = next(f for f in manifest["audit"]["findings"] if f["id"] == "markdown-alternate-broken")
            self.assertEqual({t["url"].removeprefix(self.origin) for t in broken["targets"]}, {"/blog", "/blog/one"})
            report = (site / "_audit.md").read_text(encoding="utf-8")
            self.assertIn("## llms.txt", report)
            self.assertIn("**Title:** Fixture Co", report)
            self.assertIn("| broken: Checked directly, HTTP 404. |", report)
            draft_note = (site / "_llms-txt-draft.md").read_text(encoding="utf-8")
            self.assertIn("## Strong pages your llms.txt does not list", draft_note)
            self.assertIn(f"{self.origin}/blog/one", draft_note.split("## Draft")[0])
            tasks = (site / "_tasks.md").read_text(encoding="utf-8")
            self.assertIn("llms.txt links agents cannot use", tasks)

    def test_missing_file_gets_a_finding_and_a_draft_from_the_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, site = self.capture(directory, "missing")
            ai = manifest["siteIntel"]["aiReadiness"]
            self.assertEqual(ai["llmsProbe"]["llmsTxt"]["state"], "absent")
            ids = {f["id"] for f in manifest["audit"]["findings"]}
            self.assertIn("llmstxt-missing", ids)
            missing = next(f for f in manifest["audit"]["findings"] if f["id"] == "llmstxt-missing")
            self.assertEqual(missing["tone"], "coverage", "optional, so information only")
            self.assertIn("Google Search ignores it", missing["explanation"])
            self.assertNotIn("No llms.txt", (site / "_tasks.md").read_text(encoding="utf-8"), "a missing llms.txt is not a task")
            self.assertFalse(ids & {"llmstxt-format", "llmstxt-dead-links"})
            draft = ai["llmsDraft"]["text"]
            result = llms_txt.validate_llms_txt(draft, base_url=f"{self.origin}/llms.txt")
            self.assertTrue(result["valid"])
            self.assertEqual(result["summary"], "Home for the fixture.")
            self.assertIn(f"[About]({self.origin}/about.md)", draft)
            self.assertNotIn("/blog/two", draft, "a noindex page is left out")
            self.assertNotIn("/old", draft, "a redirect is left out")
            self.assertIn("_llms-txt-draft|", (site / "_dashboard.md").read_text(encoding="utf-8"))

    def test_an_html_page_at_the_address_is_not_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, _site = self.capture(directory, "html")
            ai = manifest["siteIntel"]["aiReadiness"]
            self.assertEqual(ai["llmsProbe"]["llmsTxt"]["state"], "html")
            self.assertFalse(ai["endpoints"]["llmsTxt"])
            self.assertIn("llmstxt-serves-html", {f["id"] for f in manifest["audit"]["findings"]})


class Links(unittest.TestCase):
    def test_a_link_to_the_final_address_is_not_a_redirect(self):
        validation = llms_txt.validate_llms_txt("# N\n\n> S\n\n## D\n- [About](https://a.test/about): a\n- [Old](https://a.test/old): o\n",
                                                base_url="https://a.test/llms.txt")
        # The crawler reached /about through /old, so the node carries a redirect chain.
        nodes = [{"url": "https://a.test/about", "statusCode": 200, "redirectChain": [{"statusCode": 301}], "canonical": "https://a.test/about", "metaRobots": ""}]
        rows = {r["url"]: r["state"] for r in llms_txt.link_report(validation, nodes, {"https://a.test/old": "https://a.test/about"}, lambda u: True)}
        self.assertEqual(rows, {"https://a.test/about": "ok", "https://a.test/old": "redirect"})

    def test_unchecked_links_say_why(self):
        validation = llms_txt.validate_llms_txt("# N\n\n> S\n\n## D\n- [X](https://a.test/x): x\n", base_url="https://a.test/llms.txt")
        row = llms_txt.link_report(validation, [], {}, lambda u: True, unchecked_detail="Not captured, and the capture deadline was reached.")[0]
        self.assertEqual((row["state"], row["detail"]), ("unchecked", "Not captured, and the capture deadline was reached."))
        self.assertIn("direct checks did not reach it", llms_txt.link_report(validation, [], {}, lambda u: True, {})[0]["detail"])

    def test_findings_mention_the_draft_only_when_it_exists(self):
        ai = {"llmsProbe": {"llmsTxt": {"state": "absent", "statusCode": 404}}}
        self.assertNotIn("_llms-txt-draft.md", llms_txt.llms_findings(ai, "https://a.test")[0]["explanation"])
        ai["llmsDraft"] = {"path": "sites/a.test/_llms-txt-draft.md"}
        self.assertIn("_llms-txt-draft.md", llms_txt.llms_findings(ai, "https://a.test")[0]["explanation"])


class ServerError(unittest.TestCase):
    setUpClass = Capture.__dict__["setUpClass"]  # the same fixture site, without re-running Capture's tests
    tearDownClass = Capture.__dict__["tearDownClass"]
    capture = Capture.capture

    def test_a_server_error_is_the_one_missing_case_that_is_a_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, site = self.capture(directory, "error")
            ai = manifest["siteIntel"]["aiReadiness"]
            self.assertEqual((ai["llmsProbe"]["llmsTxt"]["state"], ai["llmsProbe"]["llmsTxt"]["statusCode"]), ("unavailable", 503))
            finding = next(f for f in manifest["audit"]["findings"] if f["id"] == "llmstxt-server-error")
            self.assertEqual(finding["tone"], "attention")
            self.assertNotIn("llmstxt-missing", {f["id"] for f in manifest["audit"]["findings"]})
            self.assertIn("llms.txt returns a server error", (site / "_tasks.md").read_text(encoding="utf-8"))


class Tasks(unittest.TestCase):
    def test_llms_tasks_close_only_when_the_llms_check_ran_again(self):
        ctx = {"complete": True, "okUrls": set(), "truncated": set(), "browserUrls": set(), "tls": True, "dns": True,
               "headers": True, "robots": True, "pageUrls": set()}
        self.assertFalse(audit_outputs._rechecked("llmstxt-dead-links", "https://a.test/gone", "", {**ctx, "llms": False}))
        self.assertTrue(audit_outputs._rechecked("llmstxt-dead-links", "https://a.test/gone", "", {**ctx, "llms": True}))
        unreached = {**ctx, "llms": True, "llmsUncheckedLinks": {"https://a.test/gone"}}
        self.assertFalse(audit_outputs._rechecked("llmstxt-dead-links", "https://a.test/gone", "", unreached),
                         "a link the direct checks did not reach this time proves nothing")
        self.assertTrue(audit_outputs._rechecked("llmstxt-format", "https://a.test/llms.txt", "", unreached))
        self.assertFalse(audit_outputs._rechecked("llmstxt-missing", "https://a.test/llms.txt", "", {**ctx, "llms": False}),
                         "a failed or refused probe never closes a task")
        self.assertTrue(audit_outputs._rechecked("markdown-alternate-broken", "https://a.test/p", "", {**ctx, "markdownChecked": {"https://a.test/p"}}))
        self.assertFalse(audit_outputs._rechecked("markdown-alternate-broken", "https://a.test/p", "", {**ctx, "markdownChecked": set()}))

    def test_a_validation_crash_is_not_a_clean_recheck(self):
        with patch("site_intel.validate_llms_txt", side_effect=RuntimeError("boom")):
            Fixture.llms_mode = "file"
            server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{server.server_port}"}), tempfile.TemporaryDirectory() as d:
                    ai = site_intel.probe_ai_and_discovery_endpoints(f"http://127.0.0.1:{server.server_port}", d, "User-agent: *\nAllow: /\n")
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(ai["llmsProbe"]["llmsTxt"]["state"], "not-checked")
        self.assertFalse(ai["endpoints"]["llmsTxt"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
