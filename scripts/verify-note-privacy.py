"""Captured notes load nothing from the network when they are opened.

A local fixture page carries third party resources in every form a note could inherit: images by
src, srcset and picture, frames, video with a poster, audio, embed, object, inline style url(),
a style block, noscript, escaped HTML shown as text, and Markdown or wikilink embeds written as
text. Offline: the only host the capture may resolve is 127.0.0.1.

Run one class against another engine checkout with WEBOBS_ENGINE_DIR=<dir> ... EndToEnd.
"""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ENGINE = Path(os.environ.get("WEBOBS_ENGINE_DIR") or Path(__file__).resolve().parents[1] / "engine")
sys.path.insert(0, str(ENGINE))
import crawl_site  # noqa: E402

CDN = "https://cdn.thirdparty.invalid"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201"
                    "e5279c1e0000000049454e44ae426082")
PAGE = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Coffee &lt;img src="{CDN}/title.gif"&gt; roasters</title>
<meta name="description" content="Fresh beans ![d]({CDN}/description.png)">
<style>body {{ background: url({CDN}/bg.png) }}</style></head>
<body><main>
<h1>Our team</h1>
<p>We roast coffee by hand in small batches every single morning for our neighbours.</p>
<img src="{CDN}/team.jpg" alt="Team photo">
<img srcset="{CDN}/wide.jpg 2x, {CDN}/narrow.jpg 1x" alt="Shop front">
<picture><source srcset="{CDN}/cup.webp" type="image/webp"><img src="{CDN}/cup.jpg" alt="Cup"></picture>
<img src="/logo.png" alt="Logo">
<iframe src="{CDN}/widget.html" title="Widget"></iframe>
<video src="{CDN}/clip.mp4" poster="{CDN}/poster.jpg" controls></video>
<audio src="{CDN}/sound.mp3" controls></audio>
<embed src="{CDN}/flash.swf"><object data="{CDN}/object.svg"></object>
<div style="background-image: url('{CDN}/inline-style.png')">Styled box with words in it.</div>
<noscript><img src="{CDN}/pixel.gif" alt="pixel"></noscript>
<p>To embed an image write &lt;img src="{CDN}/escaped.gif"&gt; or &lt;iframe src="{CDN}/escaped.html"&gt;&lt;/iframe&gt;.</p>
<p>Markdown text ![shown]({CDN}/text-markdown.png) and ![[{CDN}/text-wikilink.png]] and ![ref][r1].</p>
<p>[r1]: {CDN}/reference.png</p>
<pre><code>&lt;img src="{CDN}/code.png"&gt;</code></pre>
<p>Reach us at <a href="https://example.org/contact">the contact page</a>.</p>
</main></body></html>"""


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body, kind, code = PAGE.encode("utf-8"), "text/html; charset=utf-8", 200
        elif self.path == "/logo.png":
            body, kind, code = PNG, "image/png", 200
        else:
            body, kind, code = b"not found", "text/plain", 404
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


_REMOTE = r"(?:[A-Za-z][A-Za-z0-9+.-]*:|//)"


def network_loads(note: str) -> list[str]:
    """What Obsidian would fetch when the note is opened. Written apart from the engine's sanitizer."""
    if note.startswith("---\n"):
        end = note.find("\n---", 4)
        note = note[end + 4:] if end != -1 else note
    note = re.sub(r"(?ms)^(?:\s*>)*\s{0,3}(```|~~~).*?^(?:\s*>)*\s{0,3}\1[^\n]*$", "", note)  # code blocks
    note = re.sub(r"(`+)[^\n]*?\1", "", note)  # inline code
    loads = re.findall(r"!\[[^\]\n]*\]\(\s*<?" + _REMOTE + r"[^)\s]*", note)
    loads += re.findall(r"!\[\[\s*" + _REMOTE + r"[^\]]*", note)
    loads += [t for t in re.findall(r"<[A-Za-z][^>\n]*>?", note)
              if not re.fullmatch(r"<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*>", t)]  # raw HTML, autolinks aside
    defs = set(re.findall(r"(?m)^\s{0,3}\[([^\]]+)\]:\s*\S", note))
    loads += [m for m in re.findall(r"(?<!\\)!\[([^\]\n]*)\](?:\[([^\]\n]*)\])?(?!\()", note)
              if (m[1] or m[0]) in defs]
    return loads


class Capture(unittest.TestCase):
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

    def capture(self, directory, **options):
        resolved = []
        real = socket.getaddrinfo

        def recording(host, *args, **kwargs):
            resolved.append(host)
            return real(host, *args, **kwargs)
        settings = dict(max_pages=1, render_mode="never", download_images=False, delay_sec=0, check_external=False,
                        parallel=False, browser_audit=False, snapshot_limit=0, dns_checks=False, tls_check=False)
        settings.update(options)
        with redirect_stdout(io.StringIO()), patch.object(socket, "getaddrinfo", recording):
            manifest = crawl_site.crawl_website_to_vault(self.origin, directory, **settings)
        site = Path(directory) / "sites" / manifest["siteId"]
        notes = {p.relative_to(site).as_posix(): p.read_text(encoding="utf-8") for p in site.rglob("*.md")}
        return manifest, notes, resolved

    @staticmethod
    def home(notes):
        return next(text for text in notes.values() if "Team photo" in text)


class EndToEnd(Capture):
    def test_notes_load_nothing_when_images_are_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            _manifest, notes, resolved = self.capture(directory)
            found = {name: network_loads(text) for name, text in notes.items()}
            found = {name: loads for name, loads in found.items() if loads}
            print(f"\n  notes: {len(notes)}; notes that would load remote content: {len(found)}; "
                  f"remote loads: {sum(len(v) for v in found.values())}", file=sys.stderr)
            for name, loads in sorted(found.items()):
                print(f"    {name}: {loads[:6]}{' ...' if len(loads) > 6 else ''}", file=sys.stderr)
            self.assertEqual(found, {})
            self.assertEqual(set(resolved) - {"127.0.0.1", "localhost"}, set(), "the capture stays on its origin")

    def test_saved_image_keeps_its_local_embed(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, notes, _resolved = self.capture(directory, download_images=True)
            home = self.home(notes)
            self.assertRegex(home, r"!\[\[sites/" + re.escape(manifest["siteId"]) + r"/assets/[^\]|]+\|Logo\]\]")
            self.assertEqual(network_loads(home), [])


class Evidence(Capture):
    def test_unsaved_images_stay_as_links_and_code_stays_verbatim(self):
        with tempfile.TemporaryDirectory() as directory:
            _manifest, notes, _resolved = self.capture(directory)
            home = self.home(notes)
            self.assertIn(f"[Image not saved: Team photo]({CDN}/team.jpg)", home)
            self.assertIn("[Image not saved: Cup](", home)
            self.assertIn(f'&lt;img src="{CDN}/escaped.gif"', home, "escaped HTML is shown as text")
            self.assertIn(f'<img src="{CDN}/code.png">', home, "code keeps its exact text")
            self.assertIn(f"[Image not saved: shown]({CDN}/text-markdown.png)", home)
            self.assertIn(f"({CDN}/text-wikilink.png)", home)


class Sanitizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import note_safety
        cls.clean = staticmethod(note_safety.network_free_markdown)

    def test_each_form(self):
        cases = {
            f"![a]({CDN}/a.png)": f"[Image not saved: a]({CDN}/a.png)",
            f'![]( <{CDN}/a b.png> "t")': f"[Image not saved: image]({CDN}/a%20b.png)",
            "![x](//cdn.example/x.png)": "[Image not saved: x](//cdn.example/x.png)",
            f"![[{CDN}/w.png|Wide]]": f"[Embed not loaded: Wide]({CDN}/w.png)",
            f'<img src="{CDN}/i.png">': f'&lt;img src="{CDN}/i.png">',
            f"<video poster='{CDN}/p.jpg'></video>": f"&lt;video poster='{CDN}/p.jpg'>&lt;/video>",
            f'<div style="background:url({CDN}/s.png)">': f'&lt;div style="background:url({CDN}/s.png)">',
            "![ref][r]": "\\![ref][r]",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(self.clean(raw), expected)
                self.assertEqual(network_loads(self.clean(raw)), [])

    def test_kept_as_is(self):
        kept = ["![[sites/x/assets/logo.png|Logo]]", "![local](assets/logo.png)", "See <https://example.com/a> now.",
                "Mail <team@example.com>.", "`<img src=x>` stays code", "```html\n<iframe src=x></iframe>\n```\n",
                "> ```\n> <img src=x>\n> ```\n", "a < b and 3<4", "---\ntitle: \"<b>\"\n---\nbody\n", "[link](https://example.com)"]
        for text in kept:
            with self.subTest(text=text):
                self.assertEqual(self.clean(text), text)

    def test_idempotent(self):
        once = self.clean(PAGE)
        self.assertEqual(self.clean(once), once)


if __name__ == "__main__":
    unittest.main(verbosity=1)
