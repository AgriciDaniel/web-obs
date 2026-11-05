#!/usr/bin/env python3
"""
Full-fidelity semantic HTML-to-Markdown converter for web-obs.

Designed for real business, SaaS, documentation, and editorial websites where
news-article extractors (like trafilatura) silently drop hero copy, KPI stats,
feature cards, comparison tables, code blocks, testimonials, and FAQ accordions.

Guarantees:
- Preserves all visible sections in document order (hero, stats, cards, tables,
  fenced code blocks, blockquotes/testimonials, details/button FAQs, media).
- Never merges adjacent sibling tags without whitespace ("01" + "AUDIT" -> "01 AUDIT").
- Never emits multi-line Markdown links [line1\nline2](url), ensuring 100% valid
  single-line Obsidian [[wikilinks]].
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "bdi",
    "bdo",
    "cite",
    "code",
    "data",
    "del",
    "dfn",
    "em",
    "i",
    "ins",
    "kbd",
    "label",
    "mark",
    "q",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "time",
    "u",
    "var",
}

BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "details",
    "dialog",
    "div",
    "dl",
    "dt",
    "dd",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "summary",
    "table",
    "ul",
}

CHROME_CLASS_TOKENS = (
    "cookie-banner",
    "cookie-consent",
    "gdpr-banner",
    "popup-overlay",
    "newsletter-modal",
    "skip-link",
    "screen-reader-text",
    "sr-only",
)

DECORATIVE_BUTTON_WORDS = {
    "copy",
    "copied",
    "close",
    "menu",
    "toggle",
    "open menu",
    "close menu",
    "dismiss",
    "share",
    "prev",
    "previous",
    "next",
    "light",
    "dark",
    "system",
    "theme",
    "toggle theme",
    "copy address",
    "copy link",
    "copy code",
    "search",
}

_LAZY_IMG_ATTRS = (
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-full-url",
    "data-hi-res-src",
)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _escape_link_label(label: str) -> str:
    cleaned = _collapse_ws(label)
    cleaned = cleaned.replace("[", "(").replace("]", ")").replace("|", "-")
    return cleaned


def _best_img_url(img: Tag, base_url: str) -> Optional[str]:
    candidates: list[str] = []
    for attr in _LAZY_IMG_ATTRS:
        val = img.get(attr)
        if isinstance(val, str) and val.strip() and not val.strip().startswith("data:"):
            candidates.append(val.strip())
    src = img.get("src")
    if isinstance(src, str) and src.strip() and not src.strip().startswith("data:"):
        candidates.append(src.strip())
    if not candidates:
        for s_attr in ("data-srcset", "srcset"):
            srcset = img.get(s_attr)
            if isinstance(srcset, str) and srcset.strip():
                # Pick highest descriptor (usually last item in srcset)
                parts = [p.strip().split(" ")[0].strip() for p in srcset.split(",") if p.strip()]
                parts = [p for p in parts if p and not p.startswith("data:")]
                if parts:
                    candidates.append(parts[-1])
                    break
    if not candidates:
        return None
    full = urljoin(base_url, candidates[0])
    if candidates[0].startswith("inline-svg://"):
        return candidates[0]
    parsed = urlparse(full)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return full


def _normalize_video_embed_url(raw_url: str, base_url: str) -> Optional[tuple[str, str]]:
    if not raw_url:
        return None
    full = urljoin(base_url, raw_url.strip())
    parsed = urlparse(full)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", path)
        if m:
            vid = m.group(1)
            return ("YouTube", f"https://www.youtube.com/watch?v={vid}")
        if path.startswith("/watch"):
            return ("YouTube", full)
    if host == "youtu.be":
        vid = path.strip("/").split("/")[0]
        if vid:
            return ("YouTube", f"https://www.youtube.com/watch?v={vid}")
    if "vimeo.com" in host:
        m = re.search(r"/(?:video/)?(\d+)", path)
        if m:
            return ("Vimeo", f"https://vimeo.com/{m.group(1)}")
    if "loom.com" in host:
        return ("Loom", full.replace("/embed/", "/share/"))
    if "wistia." in host:
        return ("Wistia", full)
    return None


def _guess_code_lang(el: Tag, code_text: str) -> str:
    classes: list[str] = []
    for node in [el, *el.find_all(["code", "span"], limit=3)]:
        if isinstance(node, Tag):
            classes.extend(node.get("class") or [])
    for cls in classes:
        c = cls.lower()
        for prefix in ("language-", "lang-", "highlight-source-"):
            if c.startswith(prefix):
                return re.sub(r"[^a-z0-9+#_-]", "", c[len(prefix) :])[:16]
    stripped = code_text.strip()
    if stripped.startswith(("{", "[")) and ('"@context"' in stripped or '":' in stripped):
        return "json"
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if first_line.startswith(
        (
            "git ",
            "bash ",
            "sh ",
            "npm ",
            "npx ",
            "pnpm ",
            "yarn ",
            "curl ",
            "wget ",
            "pip ",
            "python",
            "claude",
            "/seo",
            "sudo ",
            "docker ",
            "flatpak ",
        )
    ):
        return "bash"
    if first_line.lower().startswith("powershell"):
        return "powershell"
    return ""


def _has_block_descendant(tag: Tag) -> bool:
    for desc in tag.descendants:
        if isinstance(desc, Tag) and (desc.name or "").lower() in BLOCK_TAGS:
            return True
    return False


def _is_noise_element(tag: Tag) -> bool:
    if tag.get("data-web-obs-controlled-answer") == "true":
        return False
    if tag.has_attr("hidden"):
        return True
    aria_hidden = (tag.get("aria-hidden") or "").lower().strip()
    if aria_hidden == "true":
        return True
    style = (tag.get("style") or "").lower().replace(" ", "")
    if "display:none" in style or "visibility:hidden" in style:
        # Keep hidden FAQ answer regions (which use display:none until toggled)
        role = (tag.get("role") or "").lower()
        classes = " ".join(tag.get("class") or []).lower()
        if role != "region" and "faq" not in classes and "accordion" not in classes and "tab-panel" not in classes:
            return True
    classes_and_id = f"{' '.join(tag.get('class') or [])} {tag.get('id') or ''}".lower()
    if any(tok in classes_and_id for tok in CHROME_CLASS_TOKENS):
        return True
    return False


def _is_meaningful_inline_svg(svg: Tag) -> bool:
    if (svg.get("aria-hidden") or "").lower().strip() == "true":
        return False
    if svg.find_parent(["button", "nav", "header", "footer"]) is not None:
        return False
    role = (svg.get("role") or "").lower().strip()
    has_title_or_desc = svg.find(["title", "desc"]) is not None
    has_text = bool(_collapse_ws(" ".join(t.get_text(" ", strip=True) for t in svg.find_all("text"))))

    vb = str(svg.get("viewbox") or svg.get("viewBox") or "")
    vb_nums = re.findall(r"[-+]?\d*\.?\d+", vb)
    vb_w = float(vb_nums[2]) if len(vb_nums) >= 4 else 0.0
    vb_h = float(vb_nums[3]) if len(vb_nums) >= 4 else 0.0

    w_attr = re.findall(r"\d+", str(svg.get("width") or ""))
    w_px = int(w_attr[0]) if w_attr else 0

    if role == "img" and (has_title_or_desc or vb_w >= 120 or w_px >= 120):
        return True
    if (vb_w >= 180 and vb_h >= 80) and (has_title_or_desc or has_text):
        return True
    return False


_SKIP_LINK_RE = re.compile(r"^\s*(?:skip\b|back to top\b)", re.IGNORECASE)
_LANDMARK_ROLES = {"banner": "header", "navigation": "nav", "contentinfo": "footer", "complementary": "aside"}
_REGION_LABELS = {"header": "Header", "nav": "Navigation", "footer": "Footer", "aside": "Sidebar"}


def _landmark_kind(tag: Tag) -> Optional[str]:
    name = (tag.name or "").lower()
    if name in ("header", "nav", "footer", "aside"):
        return name
    return _LANDMARK_ROLES.get((tag.get("role") or "").lower().strip())


def _region_label(tag: Tag, kind: str) -> str:
    label = _REGION_LABELS[kind]
    named = _collapse_ws(str(tag.get("aria-label") or ""))
    if named and named.lower() not in label.lower():
        label = f"{label}: {named[:40]}"
    return label


def _collect_site_regions(body: Tag, base_url: str, regions_out: Optional[list[dict]]) -> None:
    """Take site chrome out of the content flow, keeping it as labelled regions in document order.

    A header that holds the page H1 stays in the content. Landmarks inside <main> or <article>
    belong to the content (an article's own aside or byline header) and are left alone.
    """
    main_el = body.find("main") or body.find(attrs={"role": "main"})
    candidates: list[tuple[Tag, str]] = []
    for tag in body.find_all(True):
        if not isinstance(tag, Tag) or tag.parent is None:
            continue
        kind = _landmark_kind(tag)
        if not kind:
            continue
        if tag.find_parent(["main", "article"]) is not None or tag.find_parent(attrs={"role": "main"}) is not None:
            continue
        if any(tag in parent.descendants for parent, _kind in candidates):
            continue
        if kind == "header" and tag.find("h1") is not None:
            continue
        candidates.append((tag, kind))
    for tag, kind in candidates:
        if regions_out is not None:
            position = "after"
            if main_el is not None:
                # Document order relative to the main content.
                position = "before" if any(el is main_el for el in tag.find_all_next(True, limit=None)) else "after"
            elif kind in ("header", "nav"):
                position = "before"
            markdown = re.sub(r"\n{3,}", "\n\n", _render_block_children(tag, base_url)).strip()
            if markdown:
                regions_out.append({"kind": kind, "label": _region_label(tag, kind), "position": position, "markdown": markdown})
        tag.decompose()


def _prepare_content_root(soup: BeautifulSoup, base_url: str, inline_svgs_out: Optional[list[dict]] = None,
                          regions_out: Optional[list[dict]] = None) -> Tag:
    # Remove comments and non-visual tags (handle <svg> separately to preserve inline charts/diagrams!)
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    for bad in soup.find_all(["script", "style", "noscript", "template", "canvas"]):
        bad.decompose()

    # Preserve meaningful inline SVG charts/diagrams, decompose tiny decorative SVG icons
    for svg in list(soup.find_all("svg")):
        if not isinstance(svg, Tag) or svg.parent is None:
            continue
        if inline_svgs_out is not None and _is_meaningful_inline_svg(svg):
            title_el = svg.find("title")
            desc_el = svg.find("desc")
            title_txt = _collapse_ws(title_el.get_text(" ", strip=True)) if isinstance(title_el, Tag) else ""
            desc_txt = _collapse_ws(desc_el.get_text(" ", strip=True)) if isinstance(desc_el, Tag) else ""
            aria_lbl = _collapse_ws(str(svg.get("aria-label") or ""))
            alt_txt = title_txt or aria_lbl or "Inline Diagram"

            if not svg.get("xmlns"):
                svg["xmlns"] = "http://www.w3.org/2000/svg"
            raw_svg = str(svg)
            h = hashlib.sha256(raw_svg.encode("utf-8")).hexdigest()[:10]
            slug = re.sub(r"[^a-z0-9]+", "-", alt_txt.lower()).strip("-")[:36] or "diagram"
            filename = f"{slug}-{h}.svg"
            pseudo_url = f"inline-svg://{filename}"

            inline_svgs_out.append(
                {
                    "pseudo_url": pseudo_url,
                    "filename": filename,
                    "alt": alt_txt,
                    "desc": desc_txt,
                    "svg_xml": raw_svg,
                }
            )
            wrapper = soup.new_tag("figure")
            img_tag = soup.new_tag("img", src=pseudo_url, alt=alt_txt)
            wrapper.append(img_tag)
            if desc_txt and desc_txt != alt_txt:
                cap = soup.new_tag("figcaption")
                cap.string = desc_txt
                wrapper.append(cap)
            svg.replace_with(wrapper)
        else:
            svg.decompose()

    # Convert video embeds before stripping generic iframes
    for lite_yt in soup.find_all(["lite-youtube", "lite-vimeo"]):
        vid = lite_yt.get("videoid") or lite_yt.get("video-id") or ""
        title = lite_yt.get("playlabel") or lite_yt.get("title") or "Embedded Video"
        if vid:
            url = (
                f"https://www.youtube.com/watch?v={vid}"
                if "youtube" in (lite_yt.name or "")
                else f"https://vimeo.com/{vid}"
            )
            p = soup.new_tag("p")
            a = soup.new_tag("a", href=url)
            a.string = f"Watch Video: {_collapse_ws(str(title))}"
            p.append(a)
            lite_yt.replace_with(p)

    for iframe in list(soup.find_all("iframe")):
        src = iframe.get("src") or iframe.get("data-src") or ""
        info = _normalize_video_embed_url(str(src), base_url)
        if info:
            platform, watch_url = info
            title = _collapse_ws(str(iframe.get("title") or f"{platform} Video"))
            p = soup.new_tag("p")
            a = soup.new_tag("a", href=watch_url)
            a.string = f"Watch on {platform}: {title}"
            p.append(a)
            iframe.replace_with(p)
        else:
            iframe.decompose()

    # Unwrap <picture> so <img> inherits best <source srcset> if needed
    for pic in list(soup.find_all("picture")):
        img = pic.find("img")
        if img:
            best_source_url = None
            for source_el in pic.find_all("source"):
                srcset = source_el.get("srcset") or source_el.get("data-srcset")
                if isinstance(srcset, str) and srcset.strip():
                    parts = [p.strip().split(" ")[0].strip() for p in srcset.split(",") if p.strip()]
                    if parts and not parts[-1].startswith("data:"):
                        best_source_url = parts[-1]
                        break
            if best_source_url and not img.get("src"):
                img["src"] = best_source_url
            pic.replace_with(img)
        else:
            pic.decompose()

    # Hydrate JS stat counters whose static HTML text is empty or "0"
    for counter_el in soup.find_all(True):
        if not isinstance(counter_el, Tag):
            continue
        for attr in ("data-count", "data-target", "data-value", "data-number"):
            val = counter_el.get(attr)
            if isinstance(val, str) and val.strip():
                cur_txt = counter_el.get_text(strip=True)
                if cur_txt in ("", "0", "00"):
                    counter_el.string = val.strip()
                break

    # Retain answers associated with an explicit disclosure control before hidden cleanup.
    for control in soup.find_all(attrs={"aria-controls": True}):
        for target_id in str(control.get("aria-controls") or "").split():
            panel = soup.find(id=target_id)
            while isinstance(panel, Tag) and panel is not soup.body:
                panel["data-web-obs-controlled-answer"] = "true"
                panel = panel.parent

    # Remove hidden / decorative elements
    for el in list(soup.find_all(True)):
        if isinstance(el, Tag) and el.parent is not None and _is_noise_element(el):
            el.decompose()

    body = soup.body or soup
    # Skip links ("Skip to content") are keyboard helpers, not page content.
    for anchor in list(body.find_all("a", href=True)):
        if isinstance(anchor, Tag) and str(anchor.get("href") or "").startswith("#") and _SKIP_LINK_RE.match(anchor.get_text(" ", strip=True)):
            anchor.decompose()
    # Site chrome (header, navigation, footer, sidebars) leaves the content flow but is kept as regions.
    _collect_site_regions(body, base_url, regions_out)
    return body


def _render_table(table: Tag, base_url: str) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        row_vals: list[str] = []
        for cell in cells:
            txt = _collapse_ws(_render_inline_children(cell, base_url))
            txt = txt.replace("|", "\\|")
            row_vals.append(txt)
        if any(row_vals):
            rows.append(row_vals)

    if not rows:
        return ""

    col_count = max(len(r) for r in rows)
    padded = [r + [""] * (col_count - len(r)) for r in rows]

    header = padded[0]
    sep = [":---"] * col_count
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for r in padded[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _render_card_anchor(a_tag: Tag, base_url: str) -> str:
    """
    Render a block-level card link (<a href="..."><div><h3>Title</h3><p>Desc</p></div></a>)
    as a clean bullet item with a strictly single-line Markdown link.
    """
    raw_href = (a_tag.get("href") or "").strip()
    if not raw_href or raw_href.startswith(("#", "javascript:")):
        return _render_block_children(a_tag, base_url)
    full_url = urljoin(base_url, raw_href)

    # Extract distinct short text pieces from direct/leaf children in order
    pieces: list[str] = []
    heading_text = ""
    heading_el = a_tag.find(["h1", "h2", "h3", "h4", "h5", "h6", "strong"])
    if isinstance(heading_el, Tag):
        heading_text = _collapse_ws(heading_el.get_text(" ", strip=True))

    for child in a_tag.find_all(True):
        if not isinstance(child, Tag):
            continue
        # Leaf-ish block or span with no nested element children (except inline formatting)
        has_sub_blocks = any(
            isinstance(c, Tag) and (c.name or "").lower() not in ("strong", "em", "b", "i", "code", "br")
            for c in child.children
        )
        if has_sub_blocks:
            continue
        t = _collapse_ws(child.get_text(" ", strip=True))
        if t and (not pieces or pieces[-1] != t):
            pieces.append(t)

    if not pieces:
        flat = _collapse_ws(a_tag.get_text(" ", strip=True))
        if not flat:
            img = a_tag.find("img")
            if isinstance(img, Tag):
                img_url = _best_img_url(img, base_url)
                alt = _escape_link_label(str(img.get("alt") or "Image"))
                if img_url:
                    return f"![{alt}]({img_url})\n\n[{alt}]({full_url})"
            return ""
        return f"[{_escape_link_label(flat[:110])}]({full_url})"

    # Filter trailing boilerplate CTA tokens like "LEARN MORE ->"
    filtered = [
        p
        for p in pieces
        if p.upper().rstrip(" →>-") not in ("LEARN MORE", "READ MORE", "VIEW", "OPEN")
    ] or pieces

    if heading_text and heading_text in filtered:
        idx = filtered.index(heading_text)
        # Include short 2-digit prefix like "01" if immediately preceding heading
        if idx == 1 and len(filtered[0]) <= 6:
            link_title = f"{filtered[0]} - {heading_text}"
            rest = filtered[2:]
        else:
            link_title = heading_text
            rest = [p for i, p in enumerate(filtered) if i != idx]
    elif len(filtered) >= 2 and len(filtered[0]) <= 6:
        link_title = f"{filtered[0]} - {filtered[1]}"
        rest = filtered[2:]
    else:
        link_title = filtered[0]
        rest = filtered[1:]

    safe_title = _escape_link_label(link_title[:110]) or "Link"
    if rest:
        summary = " · ".join(_collapse_ws(r) for r in rest if r)
        return f"- **[{safe_title}]({full_url})**: {summary}"
    return f"- **[{safe_title}]({full_url})**"


def _render_inline_node(node: Tag | NavigableString, base_url: str) -> str:
    if isinstance(node, NavigableString):
        text = str(node)
        if not text.strip():
            return " " if (" " in text or "\n" in text or "\t" in text) else ""
        return re.sub(r"\s+", " ", text)

    if not isinstance(node, Tag):
        return ""

    name = (node.name or "").lower()
    if name == "br":
        return " "
    if name == "button":
        label = _collapse_ws(node.get_text(" ", strip=True))
        if not label or label.lower() in DECORATIVE_BUTTON_WORDS or len(label) <= 2:
            return ""
        return label
    if name == "img":
        img_url = _best_img_url(node, base_url)
        if not img_url:
            return ""
        alt = _escape_link_label(str(node.get("alt") or ""))
        return f"\n\n![{alt}]({img_url})\n\n"

    if name == "code":
        txt = _collapse_ws(node.get_text(" ", strip=True))
        if not txt:
            return ""
        return f"`{txt}`"

    if name in ("strong", "b"):
        inner = _collapse_ws(_render_inline_children(node, base_url))
        return f"**{inner}**" if inner else ""

    if name in ("em", "i"):
        inner = _collapse_ws(_render_inline_children(node, base_url))
        return f"*{inner}*" if inner else ""

    if name == "a":
        raw_href = (node.get("href") or "").strip()
        if _has_block_descendant(node):
            return "\n\n" + _render_card_anchor(node, base_url) + "\n\n"
        inner = _collapse_ws(_render_inline_children(node, base_url))
        if not inner:
            img = node.find("img")
            if isinstance(img, Tag):
                img_md = _render_inline_node(img, base_url).strip()
                return f"\n\n{img_md}\n\n" if img_md else ""
            return ""
        if not raw_href or raw_href.startswith(("#", "javascript:")):
            return inner
        full_url = urljoin(base_url, raw_href)
        safe_label = _escape_link_label(inner[:120])
        return f"[{safe_label}]({full_url})"

    return _render_inline_children(node, base_url)


def _render_inline_children(parent: Tag, base_url: str) -> str:
    parts: list[str] = []
    previous: Tag | NavigableString | None = None
    for child in parent.children:
        rendered = _render_inline_node(child, base_url)
        if not rendered:
            continue
        # "<span>Person</span>Jake" is a label styled as its own block; keep the words apart.
        if (
            parts
            and isinstance(child, NavigableString)
            and isinstance(previous, Tag)
            and (previous.name or "").lower() in ("span", "small", "label", "strong", "b", "div")
            and not parts[-1].endswith((" ", "\n"))
            and re.match(r"[A-Z0-9]", rendered)
        ):
            parts.append(" ")
        previous = child
        # Ensure adjacent sibling tags never concatenate words without space
        if (
            parts
            and isinstance(child, Tag)
            and not parts[-1].endswith((" ", "\n", "(", "[", "/", "-"))
            and not rendered.startswith((" ", "\n", ".", ",", ":", ";", "!", "?", ")", "]"))
        ):
            parts.append(" ")
        parts.append(rendered)
    joined = "".join(parts)
    # Preserve intentional paragraph breaks inserted around inline images/cards
    chunks = [ _collapse_ws(c) for c in joined.split("\n\n") ]
    return "\n\n".join(c for c in chunks if c)


def _is_compact_kv_row(div_el: Tag) -> Optional[str]:
    """
    Detect compact UI stat blocks / score bars / key-value rows built from <div>/<span>
    (e.g. <div class="stat-block"><div class="stat-val">25</div><div class="stat-label">SUB-SKILLS</div></div>)
    and format them cleanly on one bullet line instead of detached 1-word lines.
    """
    if div_el.find(["h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "pre", "blockquote", "img", "p"]):
        return None
    el_children = [c for c in div_el.children if isinstance(c, Tag)]
    if not (2 <= len(el_children) <= 4):
        return None
    # Rows holding links or buttons are actions or navigation; render them so the links survive.
    if any((c.name or "").lower() in ("a", "button") or c.find(["a", "button"]) is not None for c in el_children):
        return None

    # Do not collapse a grid of multiple cards; only leaf rows where each child has <=1 sub-tag
    segments: list[str] = []
    for ch in el_children:
        if (ch.name or "").lower() == "a" and _has_block_descendant(ch):
            return None
        deep_blocks = [
            d for d in ch.find_all( BLOCK_TAGS )
            if d is not ch
        ]
        if len(deep_blocks) > 1:
            return None
        t = _collapse_ws(ch.get_text(" ", strip=True))
        if not t:
            continue
        if len(t) > 75:
            return None
        segments.append(t)

    if 2 <= len(segments) <= 4 and sum(len(s) for s in segments) <= 120:
        return f"- **{segments[0]}**: {' · '.join(segments[1:])}"
    return None


def _render_block_node(node: Tag | NavigableString, base_url: str, list_depth: int = 0) -> str:
    if isinstance(node, NavigableString):
        t = _collapse_ws(str(node))
        return t

    if not isinstance(node, Tag):
        return ""

    name = (node.name or "").lower()

    if name in ("script", "style", "noscript", "template", "svg", "canvas"):
        return ""

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        txt = _collapse_ws(node.get_text(" ", strip=True))
        if not txt:
            return ""
        return f"{'#' * level} {txt}"

    if name == "hr":
        return "---"

    if name == "img":
        img_url = _best_img_url(node, base_url)
        if not img_url:
            return ""
        alt = _escape_link_label(str(node.get("alt") or ""))
        return f"![{alt}]({img_url})"

    if name == "figure":
        fig_parts: list[str] = []
        for img in node.find_all("img"):
            img_md = _render_block_node(img, base_url)
            if img_md:
                fig_parts.append(img_md)
        cap = node.find("figcaption")
        if isinstance(cap, Tag):
            cap_txt = _collapse_ws(_render_inline_children(cap, base_url))
            if cap_txt:
                fig_parts.append(f"*{cap_txt}*")
        if fig_parts:
            return "\n\n".join(fig_parts)

    if name == "pre":
        raw_code = node.get_text("\n", strip=False).strip("\r\n")
        if not raw_code.strip():
            return ""
        lang = _guess_code_lang(node, raw_code)
        # CommonMark: the fence must be longer than any backtick run inside, or a fence shown in the
        # code (a tutorial's "```js") would close the block early and turn the rest into page text.
        fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", raw_code)), default=0) + 1)
        return f"{fence}{lang}\n{raw_code}\n{fence}"

    if name == "table":
        return _render_table(node, base_url)

    if name == "blockquote":
        inner = _render_block_children(node, base_url, list_depth)
        if not inner:
            return ""
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in inner.splitlines())
        return quoted

    if name in ("ul", "ol"):
        ordered = name == "ol"
        items: list[str] = []
        idx = 1
        indent = "  " * list_depth
        for li in node.find_all("li", recursive=False):
            prefix = f"{idx}. " if ordered else "- "
            idx += 1
            # Separate nested lists from inline content of li
            nested_lists = [c for c in li.children if isinstance(c, Tag) and (c.name or "").lower() in ("ul", "ol")]
            for nl in nested_lists:
                nl.extract()
            li_text = _collapse_ws(_render_inline_children(li, base_url))
            line = f"{indent}{prefix}{li_text}" if li_text else ""
            sub_rendered = [_render_block_node(nl, base_url, list_depth + 1) for nl in nested_lists]
            sub_rendered = [s for s in sub_rendered if s]
            if line and sub_rendered:
                items.append(line + "\n" + "\n".join(sub_rendered))
            elif line:
                items.append(line)
            elif sub_rendered:
                items.append("\n".join(sub_rendered))
        return "\n".join(items)

    if name == "details":
        sum_el = node.find("summary")
        q_txt = ""
        if isinstance(sum_el, Tag):
            q_txt = _collapse_ws(sum_el.get_text(" ", strip=True))
            sum_el.extract()
        ans_txt = _render_block_children(node, base_url, list_depth)
        if q_txt and ans_txt:
            return f"### {q_txt}\n\n{ans_txt}"
        return ans_txt or (f"### {q_txt}" if q_txt else "")

    if name == "dl":
        dl_lines: list[str] = []
        for child in node.find_all(["dt", "dd"], recursive=False):
            cname = (child.name or "").lower()
            ctxt = _collapse_ws(_render_inline_children(child, base_url))
            if not ctxt:
                continue
            if cname == "dt":
                dl_lines.append(f"### {ctxt}")
            else:
                dl_lines.append(ctxt)
        return "\n\n".join(dl_lines)

    if name == "button":
        txt = _collapse_ws(node.get_text(" ", strip=True))
        if not txt or txt.lower() in DECORATIVE_BUTTON_WORDS or len(txt) <= 2:
            return ""
        # FAQ / Accordion button triggers
        classes = " ".join(node.get("class") or []).lower()
        if (
            node.has_attr("aria-expanded")
            or node.has_attr("aria-controls")
            or "faq" in classes
            or "accordion" in classes
            or txt.endswith("?")
        ):
            return f"### {txt}"
        return ""

    if name == "a":
        if _has_block_descendant(node):
            return _render_card_anchor(node, base_url)
        return _render_inline_node(node, base_url).strip()

    if name == "p":
        return _render_inline_children(node, base_url).strip()

    if name == "form":
        # Render any explanatory text/labels inside forms cleanly without input junk
        p_texts = [
            _collapse_ws(_render_inline_children(p, base_url))
            for p in node.find_all(["h2", "h3", "h4", "p"])
        ]
        return "\n\n".join(t for t in p_texts if t)

    # Generic container (div, section, article, main, header, aside, etc.)
    if name == "div":
        compact = _is_compact_kv_row(node)
        if compact:
            return compact

    if not _has_block_descendant(node):
        inline_res = _render_inline_children(node, base_url).strip()
        # Terminal single-command divs (e.g. <div class="cmd">git clone ...</div>)
        classes = " ".join(node.get("class") or []).lower()
        if inline_res and any(k in classes for k in ("cmd", "command", "terminal", "code-line")) and "`" not in inline_res:
            return f"`{inline_res}`"
        return inline_res

    return _render_block_children(node, base_url, list_depth)


def _render_block_children(parent: Tag, base_url: str, list_depth: int = 0) -> str:
    blocks: list[str] = []
    inline_buf: list[Tag | NavigableString] = []

    def _flush_inline_buf() -> None:
        if not inline_buf:
            return
        temp_span = BeautifulSoup("<span></span>", "html.parser").span
        assert temp_span is not None
        for item in inline_buf:
            if isinstance(item, NavigableString):
                temp_span.append(NavigableString(str(item)))
            else:
                temp_span.append(item)
        inline_buf.clear()
        rendered = _render_inline_children(temp_span, base_url).strip()
        if rendered:
            blocks.append(rendered)

    for child in list(parent.children):
        if isinstance(child, NavigableString):
            if str(child).strip():
                inline_buf.append(child)
            elif inline_buf:
                inline_buf.append(child)
            continue

        if not isinstance(child, Tag):
            continue

        cname = (child.name or "").lower()
        is_inline_only = cname in INLINE_TAGS and not (cname == "a" and _has_block_descendant(child))
        if is_inline_only or cname == "br":
            inline_buf.append(child)
        else:
            _flush_inline_buf()
            b_txt = _render_block_node(child, base_url, list_depth)
            if b_txt and b_txt.strip():
                blocks.append(b_txt.strip())

    _flush_inline_buf()

    # Merge consecutive bullet items without blank lines between them, blank lines between other blocks
    merged: list[str] = []
    for blk in blocks:
        if (
            merged
            and blk.startswith("- ")
            and "\n\n" not in blk
            and merged[-1].lstrip().startswith("- ")
            and not merged[-1].startswith("#")
        ):
            merged[-1] = merged[-1] + "\n" + blk
        else:
            merged.append(blk)

    return "\n\n".join(merged)


def convert_html_to_markdown(
    html: str,
    page_url: str,
    parser: str = "lxml",
    inline_svgs_out: Optional[list[dict]] = None,
    regions_out: Optional[list[dict]] = None,
) -> str:
    """
    Convert full page HTML into clean, structured Obsidian-ready Markdown
    preserving every section, table, code fence, card grid, stat bar, inline SVG diagram, and FAQ.
    """
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, parser)
    root = _prepare_content_root(soup, page_url, inline_svgs_out=inline_svgs_out, regions_out=regions_out)
    md = _render_block_children(root, page_url)
    # Collapse 3+ consecutive newlines down to 2
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md
