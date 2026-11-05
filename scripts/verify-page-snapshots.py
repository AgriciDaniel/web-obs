"""Full-page snapshots, end to end against a local fixture: the picture is the page at its real
height, sections sized in viewport units keep their size, pinned bottom banners are hidden, pinned
headers and sticky content stay, and very tall pages are cut at the cap and say so.

Offline: the fixture is served on 127.0.0.1 and allowed through WEB_OBS_LOCAL_TARGETS.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import page_snapshots  # noqa: E402

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html { scroll-behavior: smooth; }
body { margin: 0; }
.top { position: fixed; top: 0; left: 0; right: 0; height: 60px; background: #000000; z-index: 5; }
.hero { height: 100vh; background: #204060; }
.content { height: 3000px; background: #e0e0e0; position: relative; display: flow-root; }
.sticky { position: sticky; top: 0; height: 100px; background: #ffaa00; margin-top: 1200px; }
.footer { height: 200px; background: #10a010; }
.cookie { position: fixed; bottom: 0; left: 0; right: 0; height: 100px; background: #ff00ff; z-index: 6; }
</style></head><body>
<div class="top"></div><div class="hero"></div>
<div class="content"><div class="sticky"></div></div>
<div class="footer"></div><div class="cookie">We use cookies</div>
</body></html>"""

TALL = """<!doctype html><html><head><meta charset="utf-8"><style>html{scroll-behavior:smooth} body{margin:0} .x{height:30000px;background:#336699}</style>
</head><body><div class="x"></div></body></html>"""


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (TALL if self.path.startswith("/tall") else PAGE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def sample_pixels(image: bytes, points: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Decodes the JPEG in Chromium (no imaging library is needed) and reads the given pixels."""
    from playwright.sync_api import sync_playwright
    from browser_runtime import resolve_chromium_executable
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=resolve_chromium_executable(pw)["executablePath"])
        try:
            page = browser.new_page()
            return [tuple(p) for p in page.evaluate("""async ([src, points]) => {
              const img = new Image(); img.src = src; await img.decode();
              const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
              const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
              return points.map(([x, y]) => Array.from(ctx.getImageData(x, y, 1, 1).data.slice(0, 3)));
            }""", ["data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"), points])]
        finally:
            browser.close()


def jpeg_size(image: bytes) -> tuple[int, int]:
    i = 2
    while i < len(image):
        marker, length = image[i + 1], int.from_bytes(image[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(image[i + 7:i + 9], "big"), int.from_bytes(image[i + 5:i + 7], "big")
        i += 2 + length
    raise ValueError("not a JPEG")


def near(actual, expected, tolerance=40) -> bool:
    return all(abs(a - int(expected[k:k + 2], 16)) <= tolerance for a, k in zip(actual, (1, 3, 5)))


@unittest.skipIf(page_snapshots.sync_playwright is None, "Playwright is not installed")
class FullPageSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.server.server_port}"})
        cls.env.start()
        cls.root = tempfile.mkdtemp(prefix="web-obs-snap-")
        cls.result = page_snapshots.run_page_snapshots([f"{cls.origin}/", f"{cls.origin}/tall"], site_root=cls.root, limit=2)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()

    def entry(self, path):
        entry = self.result["pages"][f"{self.origin}{path}"]
        self.assertIsNone(entry["error"], entry)
        return entry, (Path(self.root) / entry["screenshot"]).read_bytes()

    def test_page_is_captured_at_its_real_height(self):
        entry, image = self.entry("/")
        self.assertEqual(entry["heightPx"], 800 + 3000 + 200, "a 100vh hero must not grow with the picture")
        self.assertEqual(jpeg_size(image), (1280, 4000))
        self.assertFalse(entry["truncated"])
        self.assertEqual(entry["method"], "beyond-viewport")

    def test_layout_matches_what_a_visitor_scrolls_through(self):
        _entry, image = self.entry("/")
        header, hero_mid, hero_end, content, sticky, footer, banner_zone = sample_pixels(
            image, [(640, 30), (640, 400), (640, 790), (640, 812), (640, 800 + 1250), (640, 3950), (640, 760)])
        self.assertTrue(near(header, "#000000"), f"pinned header stays at the top: {header}")
        self.assertTrue(near(hero_mid, "#204060") and near(hero_end, "#204060"), "the hero is one window tall")
        self.assertTrue(near(content, "#e0e0e0"), f"content starts right after an 800 px hero: {content}")
        self.assertTrue(near(sticky, "#ffaa00"), f"sticky content stays in its place: {sticky}")
        self.assertTrue(near(footer, "#10a010"), f"the footer is in the picture: {footer}")
        self.assertTrue(near(banner_zone, "#204060"), f"the pinned cookie banner is hidden: {banner_zone}")

    def test_smooth_scrolling_sites_are_shot_from_the_top(self):
        # With scroll-behavior: smooth the return to the top used to glide, and the picture was taken
        # part way down with the pinned header drawn mid-page.
        for path in ("/", "/tall"):
            entry, _image = self.entry(path)
            self.assertEqual(entry["scrollY"], 0, path)

    def test_hidden_overlays_are_counted(self):
        entry, _image = self.entry("/")
        self.assertEqual(entry["hiddenOverlays"], 1)

    def test_very_tall_pages_are_cut_at_the_cap_and_say_so(self):
        entry, image = self.entry("/tall")
        self.assertEqual(entry["capPx"], page_snapshots.MAX_HEIGHT_PX)
        self.assertTrue(entry["truncated"])
        self.assertGreater(entry["heightPx"], page_snapshots.MAX_HEIGHT_PX)
        self.assertEqual(jpeg_size(image), (1280, page_snapshots.MAX_HEIGHT_PX))

    def test_summary_describes_the_method(self):
        self.assertEqual(self.result["state"], "ok", self.result["detail"])
        self.assertIn("beyond the 800 px window", self.result["note"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
