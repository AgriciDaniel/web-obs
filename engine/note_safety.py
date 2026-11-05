"""Keep captured notes network free.

A note in the vault must not make Obsidian fetch anything when it is opened: no remote image
embeds, no raw HTML that loads media, frames or styles. The capture stays on the site it was asked
to read; this keeps viewing the result from contacting the site or any third party.

What is rewritten, outside code blocks and inline code, and outside the YAML frontmatter:
- `![alt](https://...)` and other schemes become `[Image not saved: alt](https://...)`, a plain link.
- `![[https://...]]` becomes `[Embed not loaded: ...](https://...)`.
- Reference style images `![alt][ref]` and `![alt]` lose their `!`, so they render as links or text.
- A raw HTML tag opener `<img`, `<iframe`, `</div` and so on becomes `&lt;...`, which Obsidian shows
  as text. Markdown autolinks such as `<https://example.com>` stay links.
Local vault embeds (`![[sites/...]]`) and relative images are kept.
"""
from __future__ import annotations

import os
import re

_SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
_FENCE = re.compile(r"^(?:\s*>)*\s{0,3}(`{3,}|~{3,})")
# A code span may wrap lines inside a paragraph but never crosses a blank line.
_CODE_SPAN = re.compile(r"(`+)(?:[^\n]|\n(?![ \t]*\n))*?(?<!`)\1(?!`)")
_INLINE_IMAGE = re.compile(
    r"!\[(?P<alt>[^\]\n]*)\]\(\s*(?P<dest><[^>\n]*>|[^)\s]+)(?P<title>\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)")
_WIKI_EMBED = re.compile(r"!\[\[(?P<target>[^\]|\n]+)(?:\|(?P<alias>[^\]\n]*))?\]\]")
_REFERENCE_IMAGE = re.compile(r"(?<!\\)!(?=\[(?!\[)[^\]\n]*\](?!\())")
_AUTOLINK = re.compile(r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+)>")
_TAG_OPEN = re.compile(r"<(?=[A-Za-z!?/])")


def _label(text: str, fallback: str) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip().replace("[", "(").replace("]", ")")
    return clean or fallback


def _destination(url: str) -> str:
    url = url.strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]
    # Percent-encode what would end or split a link destination; angle brackets would be escaped later.
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")


def _is_remote(url: str) -> bool:
    return bool(_SCHEME.match(url.strip().lstrip("<").strip()))


def _rewrite_prose(text: str) -> str:
    def inline_image(m: re.Match) -> str:
        dest = m.group("dest")
        if not _is_remote(dest):
            return m.group(0)
        return f"[Image not saved: {_label(m.group('alt'), 'image')}]({_destination(dest)})"

    def wiki_embed(m: re.Match) -> str:
        target = m.group("target").strip()
        if not _is_remote(target):
            return m.group(0)
        return f"[Embed not loaded: {_label(m.group('alias') or '', 'remote file')}]({_destination(target)})"

    text = _INLINE_IMAGE.sub(inline_image, text)
    text = _WIKI_EMBED.sub(wiki_embed, text)
    text = _REFERENCE_IMAGE.sub(r"\\!", text)
    # Escape tag openers, keeping autolinks, by splitting on them first.
    parts = _AUTOLINK.split(text)
    links = _AUTOLINK.findall(text)
    out = []
    for i, part in enumerate(parts):
        out.append(_TAG_OPEN.sub("&lt;", part))
        if i < len(links):
            out.append(links[i])
    return "".join(out)


def _split_frontmatter(text: str) -> tuple[str, str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            stop = text.find("\n", end + 4)
            stop = len(text) if stop == -1 else stop + 1
            return text[:stop], text[stop:]
    return "", text


def network_free_markdown(text: str) -> str:
    """Return the note with every network loading construct turned into plain text or a link."""
    if not text:
        return text or ""
    front, body = _split_frontmatter(text)
    out: list[str] = []
    prose: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if not prose:
            return
        chunk = "".join(prose)
        pieces, last = [], 0
        for m in _CODE_SPAN.finditer(chunk):
            pieces.append(_rewrite_prose(chunk[last:m.start()]))
            pieces.append(m.group(0))
            last = m.end()
        pieces.append(_rewrite_prose(chunk[last:]))
        out.append("".join(pieces))
        prose.clear()

    for line in body.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if fence is None and marker:
            flush()
            fence = marker.group(1)[0] * 3
            out.append(line)
        elif fence is not None:
            out.append(line)
            if marker and marker.group(1).startswith(fence):
                fence = None
        else:
            prose.append(line)
    flush()
    return front + "".join(out)


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
