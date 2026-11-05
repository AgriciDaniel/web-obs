"""Search guidance checks, matched to Google's documentation and RFC 9309.

Robots rule precedence uses Google's own worked examples. Page checks cover Googlebot's 2 MB HTML
cutoff, languages written without spaces, and wording that must not present engine conventions
as Google ranking rules. Offline.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import crawl_site  # noqa: E402
import extractor  # noqa: E402
import issue_catalog  # noqa: E402
import page_checks  # noqa: E402
import site_intel  # noqa: E402


def decide(robots, url, agent="WebObs/1.0"):
    policy = site_intel.build_robots_policy(robots, 200, user_agent=agent)
    return site_intel.robots_url_decision(policy, url)["status"]


class RobotsPrecedence(unittest.TestCase):
    def test_googles_sample_situations(self):
        # developers.google.com/search/docs/crawling-indexing/robots/robots_txt, "Order of precedence for rules"
        cases = [
            ("https://example.com/page", "Allow: /p\nDisallow: /", "allowed"),
            ("https://example.com/folder/page", "Allow: /folder\nDisallow: /folder", "allowed"),
            ("https://example.com/page.htm", "Allow: /page\nDisallow: /*.htm", "disallowed"),
            ("https://example.com/page.php5", "Allow: /page\nDisallow: /*.ph", "allowed"),
            ("https://example.com/", "Allow: /$\nDisallow: /", "allowed"),
            ("https://example.com/page.htm", "Allow: /$\nDisallow: /", "disallowed"),
        ]
        for url, rules, expected in cases:
            with self.subTest(url=url, rules=rules):
                self.assertEqual(decide("User-agent: *\n" + rules + "\n", url), expected)

    def test_longest_match_still_wins_and_encoded_octets_count_once(self):
        self.assertEqual(decide("User-agent: *\nDisallow: /a\nAllow: /a/b\n", "https://x.test/a/b/c"), "allowed")
        # /%E3%83%84 is the slash plus the three UTF-8 octets of one character: 4. /*ab is 4 too, a tie that goes
        # to allow; /*abc is 5 and wins.
        self.assertEqual(decide("User-agent: *\nAllow: /%E3%83%84\nDisallow: /*ab\n", "https://x.test/%E3%83%84ab"), "allowed")
        self.assertEqual(decide("User-agent: *\nAllow: /%E3%83%84\nDisallow: /*abc\n", "https://x.test/%E3%83%84abc"), "disallowed")

    def test_user_agent_values_are_read_as_product_tokens(self):
        for line in ("GPTBot/1.1", "GPTBot*", "gptbot"):
            with self.subTest(line=line):
                self.assertEqual(decide(f"User-agent: {line}\nDisallow: /\n", "https://x.test/a", "GPTBot"), "disallowed")
        self.assertEqual(decide("User-agent: Claude\nDisallow: /\n", "https://x.test/a", "ClaudeBot"), "allowed", "no prefix matching")

    def test_path_parameters_are_part_of_the_path(self):
        self.assertEqual(decide("User-agent: *\nDisallow: /a;jsessionid\n", "https://x.test/a;jsessionid=1?q"), "disallowed")
        self.assertEqual(decide("User-agent: *\nDisallow: /a;jsessionid\n", "https://x.test/a"), "allowed")


class AiCrawlerLine(unittest.TestCase):
    def line(self, policy):
        blocked = [b for b, s in policy.items() if s.startswith("blocked")]
        allowed = [b for b, s in policy.items() if s.startswith("allowed")]
        return crawl_site._ai_crawler_line({"aiBotsPolicy": policy, "blockedAiBots": blocked, "allowedAiBotsCount": len(allowed)})

    def test_unreadable_robots_is_no_data_not_all_allowed(self):
        policy = site_intel.parse_robots_ai_policy("User-agent: *\nAllow: /\n")
        unknown = {bot: "unknown (robots fetch incomplete)" for bot in policy}
        text = self.line(unknown)
        self.assertIn("No data: robots.txt could not be read", text)
        self.assertNotIn("allowed", text.split("**", 2)[-1].lower().replace("allowed in robots.txt", ""))

    def test_all_allowed_only_when_every_bot_is_allowed(self):
        self.assertIn("All listed AI crawlers allowed", self.line({"GPTBot": "allowed (via *)", "ClaudeBot": "allowed"}))
        mixed = self.line({"GPTBot": "allowed", "ClaudeBot": "unknown (robots fetch incomplete)"})
        self.assertIn("Unknown: `ClaudeBot`", mixed)
        self.assertNotIn("All listed", mixed)
        self.assertIn("Blocked: `GPTBot`", self.line({"GPTBot": "blocked", "ClaudeBot": "allowed"}))


def page(body, lang="en", title="A descriptive page title for tests"):
    return f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><title>{title}</title></head><body><main>{body}</main></body></html>"


def issues_for(html, url="https://x.test/p", lang_hint=None):
    data = extractor.extract_page_data(html, url, "x.test", {"content-type": "text/html; charset=utf-8"})
    return data["seo_issues"], data["page_checks"]


class PageChecks(unittest.TestCase):
    def test_html_over_googlebots_2mb_cutoff(self):
        filler = "<p>" + ("word " * 200) + "</p>"
        big = page(filler + "<script>" + ("x" * 2_050_000) + "</script>")
        issues, _ = issues_for(big)
        self.assertIn("html-over-2mb", issues)
        small, _ = issues_for(page(filler + "<script>" + ("x" * 1_900_000) + "</script>"))
        self.assertNotIn("html-over-2mb", small)
        self.assertIn("2 MB", issue_catalog.describe("html-over-3mb")["explanation"], "old captures still read correctly")

    def test_languages_written_without_spaces_are_not_called_thin(self):
        samples = {"zh": "我们的云南手工烘焙咖啡豆来自高山农场。" * 60, "ja": "九州産の手焙煎コーヒー豆を丁寧にお届けします。" * 50,
                   "th": "เมล็ดกาแฟคั่วมือจากฟาร์มบนภูเขาสูงของเรา " * 40}
        for lang, text in samples.items():
            with self.subTest(lang=lang):
                issues, checks = issues_for(page(f"<p>{text}</p>", lang=lang, title="云南手工烘焙咖啡豆"))
                self.assertNotIn("thin-content", issues)
                self.assertNotIn("title-too-short", issues, "a nine character Chinese title can be complete")
                self.assertNotIn("description-not-reflected-in-content", issues)
                self.assertFalse(checks["wordsMeasured"])
        # The script decides even when the page does not declare its language.
        _issues, checks = issues_for(page("<p>" + "我们的云南手工烘焙咖啡豆来自高山农场。" * 60 + "</p>", lang=""))
        self.assertFalse(checks["wordsMeasured"])

    def test_spaced_languages_are_still_measured(self):
        issues, checks = issues_for(page("<p>Only a few words here.</p>"))
        self.assertIn("thin-content", issues)
        self.assertTrue(checks["wordsMeasured"])
        _issues, korean = issues_for(page("<p>" + "우리 커피는 높은 산의 농장에서 옵니다. " * 80 + "</p>", lang="ko"))
        self.assertTrue(korean["wordsMeasured"], "Korean puts spaces between words")

    def test_spell_check_needs_a_declared_language(self):
        class Speller:
            def __init__(self, language="en"):
                pass

            def unknown(self, words):
                return set(words)
        with patch.object(page_checks, "SpellChecker", Speller), patch.dict(page_checks._SETTINGS, {"spell_check": True}):
            skipped = page_checks._spelling("Eine Tasse frisch gerösteter Kaffee", "")
            self.assertEqual(skipped["possibleMisspellings"], [])
            self.assertIn("does not declare its language", skipped["note"])
            self.assertIsNone(page_checks._spelling("Eine Tasse Kaffee", "de"))
            self.assertTrue(page_checks._spelling("Wordz misspeled", "en")["possibleMisspellings"])


class Wording(unittest.TestCase):
    def test_tones_follow_googles_documentation(self):
        expected = {"meta-refresh-redirect": "review", "invalid-jsonld": "review", "missing-title": "attention", "html-over-2mb": "attention"}
        for slug, tone in expected.items():
            with self.subTest(slug=slug):
                self.assertEqual(issue_catalog.describe(slug)["tone"], tone)
        self.assertEqual(issue_catalog.describe("heading-level-skip")["category"], "accessibility")

    def test_conventions_are_not_presented_as_ranking_rules(self):
        thin = issue_catalog.describe("thin-content")
        self.assertIn("Google has no minimum word count", thin["explanation"])
        self.assertNotIn("weak for pages meant to rank", thin["explanation"])
        self.assertIn("does not affect Search on its own", issue_catalog.describe("multiple-h1")["explanation"])
        self.assertIn("Google recommends them", issue_catalog.describe("url-non-ascii")["explanation"])
        self.assertIn("Google follows it", issue_catalog.describe("meta-refresh-redirect")["explanation"])
        self.assertIn("main heading", issue_catalog.describe("missing-title")["explanation"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
