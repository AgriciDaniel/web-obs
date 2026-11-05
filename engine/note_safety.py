"""Keep captured notes network free.

A note in the vault must not make Obsidian fetch anything when it is opened: no remote image
embeds, no raw HTML that loads media, frames or styles. The capture stays on the site it was asked
to read; this keeps viewing the result from contacting the site or any third party.

Only two Markdown constructs can load anything: an image or embed (`![`) and raw HTML (`<` followed
by a letter, `/`, `!` or `?`). Every one of them is made inert, so safety does not depend on knowing
which lines are code:

- In prose, a remote `![alt](url)` becomes `[Image not saved: alt](url)`, a remote `![[https://...]]`
  becomes `[Embed not loaded: ...](url)`, any other `![` that is not a local image or embed gets a
  zero-width space after the `!`, and a raw HTML tag opener becomes `&lt;`, shown as text. Markdown
  autolinks such as `<https://example.com>` stay links.
- In code (fenced or indented code blocks, inline code) and in the YAML frontmatter, where text
  shows as written, a zero-width space goes after `<` and between `!` and `[`. The text looks the
  same, and if a line was misjudged as code it still cannot load anything.

Code is found the CommonMark way: a closing fence uses the opener's character, is at least as long
and has no info string; a fence ends with its blockquote or list item; an unclosed fence runs to
the end; four spaces of indent outside a paragraph is code. Local vault embeds (`![[sites/...]]`)
and relative images are kept.
"""
from __future__ import annotations

import os
import re

ZW = "​"  # zero-width space
_SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//|\\\\)")

# A destination may hold balanced parentheses, as CommonMark allows: a_(1).png stays one link.
_DEST = r"<[^<>\n]*>|(?:[^\s()<>]|\((?:[^\s()<>]|\([^\s()<>]*\))*\))+"
_TITLE = r"(?:\"[^\"]*\"|'[^']*'|\([^()]*\))"
# Alt text may wrap onto following lines of the same paragraph, never across a blank line.
_ALT = r"(?:[^\[\]\n]|\n(?![ \t>]*\n)|\[[^\[\]\n]*\])*"
_IMAGE = re.compile(r"!\[(?P<alt>" + _ALT + r")\]\(\s*(?P<dest>" + _DEST + r")(?:\s+" + _TITLE + r")?\s*\)")
_EMBED = re.compile(r"!\[\[(?P<target>[^\]|\n]+)(?:\|(?P<alias>[^\]\n]*))?\]\]")
_CODE_SPAN = re.compile(r"(?<!`)(?P<ticks>`+)(?!`)(?:[^`\n]|`+(?!(?P=ticks)(?!`))|\n(?![ \t>]*\n))+?(?<!`)(?P=ticks)(?!`)")
_AUTOLINK = re.compile(r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+)>")
_TAG_OPEN = re.compile(r"<(?=[A-Za-z!?/])")

_QUOTE = re.compile(r" {0,3}> ?")
_LIST = re.compile(r"( {0,3})([-+*]|\d{1,9}[.)])( {1,4}(?=\S)| *$)")
_FENCE_OPEN = re.compile(r" {0,3}(?P<run>`{3,}(?=[^`]*$)|~{3,})(?P<info>.*)$")
_BLOCK_START = re.compile(r" {0,3}(?:>|#{1,6}(?:\s|$)|(?:[-*_][ \t]*){3,}$|`{3,}|~{3,}|[-+*](?:\s|$)|1[.)](?:\s|$))")


def inert(text: str) -> str:
    """Make text unable to load anything while it looks the same where it shows as written."""
    return _TAG_OPEN.sub("<" + ZW, text.replace("![", "!" + ZW + "["))


def _label(text: str, fallback: str) -> str:
    clean = re.sub(r"\s+", " ", re.sub(r"(?m)^[ \t]*(?:>[ \t]?)+", " ", text or "")).strip()
    return clean.replace("[", "(").replace("]", ")") or fallback


def _destination(url: str) -> str:
    url = url.strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]
    return url.replace(" ", "%20").replace("<", "%3C").replace(">", "%3E")


def _is_remote(url: str) -> bool:
    return bool(_SCHEME.match(url.strip().lstrip("<").strip()))


def _images_and_embeds(text: str) -> str:
    out, last = [], 0
    for m in sorted(list(_IMAGE.finditer(text)) + list(_EMBED.finditer(text)), key=lambda m: m.start()):
        if m.start() < last:
            continue
        out.append(text[last:m.start()].replace("![", "!" + ZW + "["))
        if "dest" in m.groupdict():
            dest = m.group("dest")
            out.append(f"[Image not saved: {_label(m.group('alt'), 'image')}]({_destination(dest)})" if _is_remote(dest) else m.group(0))
        else:
            target = m.group("target").strip()
            out.append(f"[Embed not loaded: {_label(m.group('alias') or '', 'remote file')}]({_destination(target)})"
                       if _is_remote(target) else m.group(0))
        last = m.end()
    out.append(text[last:].replace("![", "!" + ZW + "["))
    return "".join(out)


def _escape_tags(text: str) -> str:
    out, last = [], 0
    for m in _AUTOLINK.finditer(text):
        out.append(_TAG_OPEN.sub("&lt;", text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_TAG_OPEN.sub("&lt;", text[last:]))
    return "".join(out)


def _rewrite_prose(chunk: str) -> str:
    out, last = [], 0
    for m in _CODE_SPAN.finditer(chunk):
        out.append(_escape_tags(_images_and_embeds(chunk[last:m.start()])))
        out.append(inert(m.group(0)))
        last = m.end()
    out.append(_escape_tags(_images_and_embeds(chunk[last:])))
    return "".join(out)


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


def code_lines(lines: list[str]) -> list[bool]:
    """Which lines CommonMark renders as code. Blockquotes, list items, fences and indented code."""
    containers: list[tuple] = []  # ("q",) or ("l", content_indent)
    fence = None  # (char, length, container depth)
    paragraph = False
    result = []
    for raw in lines:
        line = raw.rstrip("\n").expandtabs(4)
        rest, matched = line, 0
        for kind in containers:
            if kind[0] == "q":
                m = _QUOTE.match(rest)
                if not m:
                    break
                rest = rest[m.end():]
            elif rest.strip() == "":
                rest = ""
            elif _indent(rest) >= kind[1]:
                rest = rest[kind[1]:]
            else:
                break
            matched += 1
        if fence and matched == len(containers) and fence[2] == len(containers):
            closer = re.match(r" {0,3}(" + re.escape(fence[0]) + "{" + str(fence[1]) + r",})[ \t]*$", rest)
            if closer:
                fence = None
            result.append(True)
            continue
        if matched < len(containers):
            lazy = paragraph and fence is None and rest.strip() and not _BLOCK_START.match(rest)
            if lazy:
                result.append(False)
                continue
            containers = containers[:matched]
            fence = None
            paragraph = False
        # New containers.
        while True:
            q = _QUOTE.match(rest)
            if q:
                containers.append(("q",))
                rest = rest[q.end():]
                paragraph = False
                continue
            li = _LIST.match(rest)
            if li and not (paragraph and li.group(3).strip() == "" and not rest[li.end():].strip()):
                spaces = len(li.group(3))
                width = len(li.group(1)) + len(li.group(2)) + (spaces if 0 < spaces <= 4 else 1)
                containers.append(("l", width))
                rest = rest[li.end():]
                paragraph = False
                continue
            break
        if rest.strip() == "":
            paragraph = False
            result.append(False)
            continue
        if not paragraph and _indent(rest) >= 4:
            result.append(True)  # indented code
            continue
        opener = _FENCE_OPEN.match(rest)
        if opener:
            fence = (opener.group("run")[0], len(opener.group("run")), len(containers))
            paragraph = False
            result.append(True)
            continue
        paragraph = not re.match(r" {0,3}(?:#{1,6}(?:\s|$)|(?:[-*_][ \t]*){3,}$)", rest)
        result.append(False)
    return result


def _split_frontmatter(text: str) -> tuple[str, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            stop = text.find("\n", end + 4)
            stop = len(text) if stop == -1 else stop + 1
            return text[:stop], text[stop:]
    return "", text


def network_free_markdown(text: str) -> str:
    """Return the note with every network loading construct made inert."""
    if not text:
        return text or ""
    front, body = _split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    prose: list[str] = []
    for line, is_code in zip(lines, code_lines(lines)):
        if is_code:
            if prose:
                out.append(_rewrite_prose("".join(prose)))
                prose.clear()
            out.append(inert(line))
        else:
            prose.append(line)
    if prose:
        out.append(_rewrite_prose("".join(prose)))
    return inert(front) + "".join(out)


def make_notes_network_free(root: str) -> int:
    """Rewrite every Markdown note under root in place. Returns how many notes changed."""
    changed = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            safe = network_free_markdown(text)
            if safe != text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(safe)
                changed += 1
    return changed
