"""Which inline SVG the capture saves as the site's logo, and that it is saved as valid, scalable SVG.

Offline: the fixtures have no stylesheets or images, so nothing is fetched.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import brand_and_dns  # noqa: E402

HOME = "https://brand.example/"


class FakeDownloader:
    def __init__(self):
        self.saved = None

    def download_image(self, _url):
        return None

    def save_inline_svg(self, _key, name, markup):
        self.saved = markup
        return name


def saved_logo(body: str) -> tuple[dict, str | None]:
    downloader = FakeDownloader()
    kit = brand_and_dns.extract_observed_brand_kit(f"<!doctype html><html><head></head><body>{body}</body></html>", HOME,
                                                   downloader=downloader, domain_folder="brand.example")
    return kit, downloader.saved


LOGO = '<svg viewBox="0 0 120 40"><defs><linearGradient id="g" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#e07850"/></linearGradient></defs><path fill="url(#g)" d="M0 0h120v40H0z"/></svg>'
SUN = '<svg class="rk-sun" fill="none" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2"/></svg>'


class InlineSvgLogo(unittest.TestCase):
    def test_svg_inside_the_home_link_is_the_logo(self):
        kit, svg = saved_logo(f'<header><button aria-label="Toggle theme">{SUN}</button><a href="/">{LOGO}</a></header>')
        self.assertEqual(kit["localLogoAsset"], "sites/brand.example/assets/brand-logo.svg")
        self.assertIn("linearGradient", svg)
        self.assertNotIn("rk-sun", svg)

    def test_case_sensitive_svg_names_survive_the_html_parser(self):
        _kit, svg = saved_logo(f'<header><a href="https://brand.example/">{LOGO}</a></header>')
        for name in ("viewBox=", "<linearGradient", "</linearGradient>", "gradientUnits="):
            self.assertIn(name, svg)
        for broken in ("viewbox=", "lineargradient", "gradientunits"):
            self.assertNotIn(broken, svg)
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)

    def test_interface_icons_are_never_taken_as_the_logo(self):
        for body in (
            f"<header>{SUN}</header>",                                   # no logo signal at all
            f'<header><button><a href="/">{LOGO}</a></button></header>',  # inside a button
            f'<header><a href="/" role="button">{LOGO}</a></header>',
            f'<header><a href="/search">{LOGO}</a></header>',            # links somewhere else
            f'<nav><a href="/">{SUN}</a></nav>',                         # home link, but an icon by name
        ):
            kit, svg = saved_logo(body)
            self.assertIsNone(svg, body)
            self.assertIsNone(kit["localLogoAsset"], body)

    def test_a_named_logo_container_counts_without_a_home_link(self):
        kit, svg = saved_logo(f'<div class="site-logo">{LOGO}</div>')
        self.assertIsNotNone(svg)
        self.assertEqual(kit["localLogoAsset"], "sites/brand.example/assets/brand-logo.svg")
        _kit, svg = saved_logo(f'<header><a href="/"><svg class="logo-icon" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg></a></header>')
        self.assertIsNotNone(svg, 'an explicit "logo" name wins over the word "icon"')

    def test_case_restoration_leaves_other_markup_alone(self):
        source = '<svg viewbox="0 0 1 1" data-viewbox="x"><title>viewbox lineargradient</title><path d="M0 0"/></svg>'
        restored = brand_and_dns._restore_svg_case(source)
        self.assertIn('viewBox="0 0 1 1"', restored)
        self.assertIn('data-viewbox="x"', restored)
        self.assertIn("<title>viewbox lineargradient</title>", restored)


if __name__ == "__main__":
    unittest.main(verbosity=1)
