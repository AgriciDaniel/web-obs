"""Rendered notes load nothing: a CommonMark renderer is the judge, not the sanitizer.

Every sanitized note is rendered with markdown-it-py (CommonMark preset, raw HTML on, as Obsidian
renders raw HTML), and the HTML is checked for anything that would fetch: an element outside the
Markdown set (img, source, video, audio, iframe, embed, object, link, image and the rest), an img
whose src is not local, or an Obsidian embed `![[https://...]]` left in prose. The corpus is the
privacy review's cases, a converter case with a fence shown inside <pre>, a full capture of the
note privacy fixture, and a generated set of fences (length 3 to 5, backtick and tilde, with and
without info strings, nested fence lines, inside quotes and lists, indented, closed and unclosed),
each followed by remote images and raw HTML.

markdown-it-py runs in a separate interpreter (`python3` with markdown_it importable). Offline.
Run against another engine checkout with WEBOBS_ENGINE_DIR=<dir>.
"""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ENGINE = Path(os.environ.get("WEBOBS_ENGINE_DIR") or REPO / "engine")
sys.path.insert(0, str(ENGINE))
import crawl_site  # noqa: E402
import markdown_converter  # noqa: E402
import note_safety  # noqa: E402

ZW = "\u200b"
R = "https://e.invalid"

RENDER = r"""
import json, re, sys
from html.parser import HTMLParser
from markdown_it import MarkdownIt
md = MarkdownIt("commonmark", {"html": True})
MARKDOWN_TAGS = {"p", "a", "code", "pre", "blockquote", "ul", "ol", "li", "em", "strong", "hr", "br", "img",
                 "h1", "h2", "h3", "h4", "h5", "h6"}
REMOTE = re.compile(r"^\s*(?:[A-Za-z][A-Za-z0-9+.-]*:|//|\\\\)")
class Check(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.loads, self.code, self.prose, self.depth, self.buf = [], [], [], 0, []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in MARKDOWN_TAGS:
            self.loads.append(f"<{tag} {attrs}>")
        elif tag == "img" and (REMOTE.match(attrs.get("src") or "") or attrs.get("srcset")):
            self.loads.append(f"<img {attrs}>")
        for key in ("style", "background", "poster", "srcset", "data"):
            if key in attrs:
                self.loads.append(f"<{tag} {key}>")
        if tag == "code":
            self.depth += 1
            self.buf = []
    def handle_endtag(self, tag):
        if tag == "code" and self.depth:
            self.depth -= 1
            self.code.append("".join(self.buf))
    def handle_data(self, data):
        (self.buf if self.depth else self.prose).append(data)
out = []
for doc in json.load(sys.stdin):
    html = md.render(doc)
    infos, inline = [], []
    for token in md.parse(doc):
        if token.type == "fence":
            infos.append(token.info)
        for child in token.children or []:
            if child.type == "code_inline":
                inline.append(child.content)
    c = Check(); c.feed(html); c.close()
    prose = "".join(c.prose)
    c.loads += [m.group(0) for m in re.finditer(r"!\[\[\s*(?:[A-Za-z][A-Za-z0-9+.-]*:|//)[^\]]*", prose)]
    out.append({"loads": c.loads, "code": c.code, "prose": prose, "infos": infos, "inline": inline})
json.dump(out, sys.stdout)
"""


def renderer() -> str:
    for candidate in (sys.executable, shutil.which("python3"), "/usr/bin/python3"):
        if candidate and subprocess.run([candidate, "-c", "import markdown_it"], capture_output=True).returncode == 0:
            return candidate
    raise RuntimeError("markdown-it-py is needed for this check: pip install --user markdown-it-py")


def render(docs: list[str]) -> list[dict]:
    run = subprocess.run([renderer(), "-P", "-c", RENDER], input=json.dumps(docs), capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        raise RuntimeError(run.stderr[-2000:])
    return json.loads(run.stdout)


REVIEW = {
    "info-string line inside a fence": f"```\ncode\n```js\nmore\n```\n![x]({R}/i.png)\n```\n",
    "fence in a quote, quote ends": f"> ```\n> code\n\n![x]({R}/i.png)\n",
    "short fence inside a longer one": f"````\n```\n````\n![x]({R}/i.png)\n",
    "indented fence line": f"    ```\n![x]({R}/i.png)\n",
    "alt text over two lines": f"![a\nb]({R}/i.png)\n",
    "html entity": f"&#60;img src={R}/i.png>\n",
    "tag with a colon": f"<img:x src={R}/i.png>\n",
    "parentheses in the URL": f"![a]({R}/a_(1).png)\n",
    "unclosed fence": f"```\n![x]({R}/i.png)\n",
    "angle destination": f"![a](<{R}/i.png>)\n",
    "reader e2e note": f'```\nInstall:\n```js\nnpm install\n```\n<img src="{R}/badge.svg" alt="build">\n```\n\nThat is all.\n',
    "fence in a list, list ends": f"- ```\n  code\n```\n<img src={R}/a.png>\n```\n![x]({R}/b.png)\n",
    "indented list fence, then top level": f"- item\n  ```\ntext\n```\naaa\n```\n![x]({R}/i.png)\n",
    "tilde fence closed by backticks": f"~~~\n```\n![x]({R}/i.png)\n",
    "reference image": f"![r][1]\n\n[1]: {R}/r.png\n",
    "obsidian embed": f"![[{R}/w.png]]\n",
    "frontmatter": f"---\ntitle: \"![t]({R}/t.png) <img src={R}/t2.png>\"\n---\nbody\n",
}

PRE_PAGE = f"""<html><body><main>
<h1>Writing Markdown with code and images</h1>
<p>This tutorial shows the raw Markdown source of a short README file for our readers.</p>
<pre><code>Install:
```js
npm install
```
&lt;img src="{R}/badge.svg" alt="build"&gt;
````
four
````</code></pre>
<p>That is all you need to get started with the project today, thanks for reading.</p>
</main></body></html>"""
PRE_TEXT = f'Install:\n```js\nnpm install\n```\n<img src="{R}/badge.svg" alt="build">\n````\nfour\n````'

# Fence languages that Obsidian or a vault plugin renders as live content, written down here apart from the
# engine's allowlist: Obsidian core (mermaid), community plugins (chartsview, dataview, dataviewjs, base, query,
# tasks, kanban, plantuml, tikz, chart...), and made-up names standing in for a vault's own plugins
# (plugin-agent, custom-flow): the allowlist must drop names it has never heard of.
LIVE_RENDERERS = {"mermaid", "chartsview", "agent", "plugin-agent", "custom-flow", "base", "query", "dataview", "dataviewjs",
                  "tasks", "kanban", "plantuml", "tikz", "chart", "abc", "music-abc", "gnuplot", "excalidraw", "math"}
RENDERER_HTML = '<p>Ordinary words on this page so the converter keeps the main content block intact here.</p>'
RENDERER_PAGES = {
    f"{attr}{lang}": f'<html><body><main><h1>Docs</h1>{RENDERER_HTML}<pre><code class="{attr}{lang}">x: 1\n'
                      f'img: "{R}/r.png"</code></pre>{RENDERER_HTML}</main></body></html>'
    for lang in ("chartsview", "mermaid", "plugin-agent", "agent", "custom-flow", "dataviewjs", "base", "tasks", "python")
    for attr in ("language-", "lang-", "highlight-source-")}
RENDERER_DIRECT = {
    "mermaid": f"```mermaid\nflowchart LR\n  A@{{ img: \"{R}/m.png\" }}\n```\n",
    "tilde chartsview": f"~~~chartsview\ntype: Graph\nimg: '{R}/c.png'\n~~~\n",
    "spaced plugin-agent": "``` plugin-agent\nprompt: hello\npersist: true\n```\n",
    "upper case": "```MERMAID\ngraph TD\n```\n",
    "braced": "```{mermaid}\ngraph TD\n```\n",
    "language first, renderer second": "```js mermaid\nx\n```\n",
    "in a quote": "> ```custom-flow\n> nodes: []\n> ```\n",
    "in a list": "- item\n\n  ````dataviewjs\n  dv.el('img', '')\n  ````\n",
    "dataview inline": f"Run `$= dv.el('img', '', {{attr: {{src: '{R}/d.png'}}}})` and `= this.file.name` and ` $=x`.\n",
}

CONTAINERS = [("", ""), ("> ", "> "), ("- ", "  "), ("1. ", "   "), ("  ", "  "), ("    ", "    "),
              ("> - ", ">   "), ("- ", "- "), ("> ", "")]
TAILS = [["", f"![x]({R}/t1.png)", f'<img src="{R}/t2.png">', "![a", f"b]({R}/t3.png)", f"![p]({R}/a_(1).png)"],
         [f"![x]({R}/t4.png) and <iframe src={R}/f.html></iframe>", f"<video poster={R}/p.jpg></video>"]]


def generated() -> list[str]:
    docs = []
    for ch, n, info, inner, (first, cont), closed, tail in itertools.product(
            "`~", (3, 4, 5), ("", "js", "mermaid"), [None] + [(m, i) for m in (3, 4, 5) for i in ("", "js")],
            CONTAINERS, (True, False), TAILS):
        lines = [first + ch * n + info, cont + f"code <img src={R}/c1.png>", cont + f"![in]({R}/c2.png)"]
        if inner:
            lines.append(cont + ch * inner[0] + inner[1])
        lines.append(cont + f"after ![x]({R}/c3.png) <img src={R}/c4.png>")
        if closed:
            lines.append(cont + ch * n)
        docs.append("\n".join(lines + tail) + "\n")
    return docs


def fixture_notes() -> list[str]:
    spec = importlib.util.spec_from_file_location("note_privacy", REPO / "scripts" / "verify-note-privacy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Capture.setUpClass()
    try:
        case = module.Capture()
        with tempfile.TemporaryDirectory() as directory:
            _manifest, notes, _resolved = case.capture(directory)
        return list(notes.values())
    finally:
        module.Capture.tearDownClass()


class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        md = markdown_converter.convert_html_to_markdown(PRE_PAGE, "https://site.example/")
        cls.pre_note = note_safety.network_free_markdown(
            crawl_site.rewrite_markdown_for_obsidian(md, "https://site.example/", {}, {}, {}, "site.example"))
        originals = {f"review: {k}": v for k, v in REVIEW.items()}
        for key, page in RENDERER_PAGES.items():
            originals[f"renderer page: {key}"] = crawl_site.rewrite_markdown_for_obsidian(
                markdown_converter.convert_html_to_markdown(page, "https://docs.example/"), "https://docs.example/", {}, {}, {}, "docs.example")
        for key, text in RENDERER_DIRECT.items():
            originals[f"renderer: {key}"] = text
        originals["converter: fence shown in <pre>"] = crawl_site.rewrite_markdown_for_obsidian(
            md, "https://site.example/", {}, {}, {}, "site.example")
        for i, note in enumerate(fixture_notes()):
            originals[f"fixture note {i}"] = note  # already sanitized by the capture; counts below allow for it
        cls.generated = generated()
        for i, doc in enumerate(cls.generated):
            originals[f"generated {i}"] = doc
        cls.originals = originals
        cls.corpus = {name: note_safety.network_free_markdown(text) for name, text in originals.items()}
        cls.rendered = dict(zip(cls.corpus, render(list(cls.corpus.values()))))
        # Obsidian shows frontmatter as properties, so the code tracking measure reads note bodies only.
        bodies = [note_safety._split_frontmatter(text)[1] for text in cls.corpus.values()]
        cls.bodies = dict(zip(cls.corpus, render(bodies)))

    def test_nothing_rendered_loads_anything(self):
        bad = {name: r["loads"] for name, r in self.rendered.items() if r["loads"]}
        groups = {}
        for name in bad:
            groups.setdefault(name.split(":")[0].rstrip("0123456789 "), []).append(name)
        print(f"\n  rendered {len(self.rendered)} notes ({len(self.generated)} generated); "
              f"notes that load remote content: {len(bad)}", file=sys.stderr)
        for group, names in groups.items():
            print(f"    {group}: {len(names)}, e.g. {names[0]}: {bad[names[0]][:3]}", file=sys.stderr)
        self.assertEqual(bad, {})

    def test_no_fence_names_a_live_renderer(self):
        allowed = getattr(note_safety, "PLAIN_CODE_LANGUAGES", None)
        live, unlisted, dataview = {}, {}, {}
        for name, r in self.rendered.items():
            words = [(info.split() or [""])[0].strip("{}").lower() for info in r["infos"]]
            if any(w in LIVE_RENDERERS for w in words):
                live[name] = r["infos"]
            if allowed is not None and any(w and w not in allowed for w in words):
                unlisted[name] = r["infos"]
            if any(code.lstrip().startswith(("=", "$=")) for code in r["inline"]):
                dataview[name] = r["inline"]
        print(f"\n  fences naming a live renderer: {len(live)} notes; outside the allowlist: {len(unlisted)}; "
              f"inline Dataview queries: {len(dataview)}", file=sys.stderr)
        for group in (live, dataview):
            for name in list(group)[:3]:
                print(f"    {name}: {group[name][:3]}", file=sys.stderr)
        self.assertEqual(live, {})
        self.assertEqual(unlisted, {})
        self.assertEqual(dataview, {})
        kept = [i for n, r in self.rendered.items() if n.startswith("renderer page: language-python") for i in r["infos"]]
        self.assertEqual(kept, ["python"], "a plain language keeps its name")

    def test_code_shown_in_pre_stays_one_code_block_with_its_text(self):
        code = self.rendered["converter: fence shown in <pre>"]["code"]
        self.assertEqual([c.replace(ZW, "") for c in code], [PRE_TEXT + "\n"])

    def test_prose_images_become_labelled_links(self):
        self.assertIn(f"[Image not saved: a]({R}/a_(1).png)", self.corpus["review: parentheses in the URL"])
        self.assertIn(f"[Image not saved: a b]({R}/i.png)", self.corpus["review: alt text over two lines"])
        self.assertIn(f"[Image not saved: x]({R}/i.png)", self.corpus["review: fence in a quote, quote ends"])
        self.assertIn(f"[Image not saved: x]({R}/i.png)", self.corpus["review: short fence inside a longer one"])

    def test_code_is_found_where_commonmark_finds_it(self):
        # Cosmetic only, never a load: prose escapes left inside rendered code, or zero-width spaces in prose.
        # Count only what the sanitizer added: escapes beyond those already in the text, and "<" marks in prose
        # (a zero-width space after "!" in prose is the intended fallback for reference images).
        def added(name, needle, texts):
            return sum(t.count(needle) for t in texts) > self.originals[name].count(needle)
        escaped_code = [n for n, r in self.bodies.items() if added(n, "&lt;", r["code"]) or added(n, "Image not saved", r["code"])]
        marked_prose = [n for n, r in self.bodies.items() if "<" + ZW in r["prose"]]
        print(f"\n  code tracking: {len(escaped_code)} notes with prose escapes in code, "
              f"{len(marked_prose)} with code marks in prose", file=sys.stderr)
        for label, names in (("prose escapes in code", escaped_code), ("code marks in prose", marked_prose)):
            for name in names[:4]:
                print(f"    {label}: {name}: {self.corpus[name][:160]!r}", file=sys.stderr)
        self.assertEqual(escaped_code, [])
        self.assertEqual(marked_prose, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
