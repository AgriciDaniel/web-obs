#!/usr/bin/env python3
"""
Observed brand and design declarations from website HTML and linked CSS.
No external enrichment services or API integrations are used.

All CSS colors and typography tokens are extracted strictly from declared HTML/CSS
sources with exact file + selector locators (never guessed visually).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from html_tail import keep_trailing_content
from bs4 import BeautifulSoup, Tag

from url_safety import (
    DEFAULT_REQUEST_HEADERS,
    URLSafetyError,
    decode_body,
    safe_requests_session,
    validate_url_strict,
)

try:
    import lxml  # noqa: F401

    _HTML_PARSER = "lxml"
except ImportError:
    _HTML_PARSER = "html.parser"

# HTML parsers lowercase every tag and attribute name, but SVG names are case-sensitive: a saved
# logo with "viewbox" or "lineargradient" renders unscaled or loses its gradients. These are the
# camelCase names from the SVG 1.1 and 2 specifications.
_SVG_CAMEL_NAMES = {name.lower(): name for name in (
    "altGlyph altGlyphDef altGlyphItem animateColor animateMotion animateTransform clipPath feBlend "
    "feColorMatrix feComponentTransfer feComposite feConvolveMatrix feDiffuseLighting feDisplacementMap "
    "feDistantLight feDropShadow feFlood feFuncA feFuncB feFuncG feFuncR feGaussianBlur feImage feMerge "
    "feMergeNode feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence "
    "foreignObject glyphRef linearGradient radialGradient textPath "
    "attributeName attributeType baseFrequency baseProfile calcMode clipPathUnits diffuseConstant edgeMode "
    "filterUnits gradientTransform gradientUnits kernelMatrix kernelUnitLength keyPoints keySplines keyTimes "
    "lengthAdjust limitingConeAngle markerHeight markerUnits markerWidth maskContentUnits maskUnits numOctaves "
    "pathLength patternContentUnits patternTransform patternUnits pointsAtX pointsAtY pointsAtZ preserveAlpha "
    "preserveAspectRatio primitiveUnits refX refY repeatCount repeatDur requiredExtensions requiredFeatures "
    "specularConstant specularExponent spreadMethod startOffset stdDeviation stitchTiles surfaceScale "
    "systemLanguage tableValues targetX targetY textLength viewBox viewTarget xChannelSelector "
    "yChannelSelector zoomAndPan"
).split()}
_SVG_TAG_RE = re.compile(r"<(/?)([A-Za-z][\w:-]*)([^<>]*)>")
_SVG_ATTR_NAME_RE = re.compile(r"(\s)([A-Za-z][\w:-]*)(?=\s*=)")
# Words that mark interface icons (theme toggles, menus, search) rather than a brand mark.
_UI_ICON_WORDS = {"icon", "sun", "moon", "theme", "toggle", "menu", "hamburger", "burger", "search", "close",
                  "chevron", "arrow", "caret", "cart", "bag", "user", "account", "social", "dropdown", "mode"}


def _restore_svg_case(markup: str) -> str:
    def tag(match: re.Match) -> str:
        name = _SVG_CAMEL_NAMES.get(match.group(2).lower(), match.group(2))
        attrs = _SVG_ATTR_NAME_RE.sub(lambda a: a.group(1) + _SVG_CAMEL_NAMES.get(a.group(2).lower(), a.group(2)), match.group(3))
        return f"<{match.group(1)}{name}{attrs}>"
    return _SVG_TAG_RE.sub(tag, markup)


def _labels(tag: Tag) -> str:
    return f"{' '.join(tag.get('class') or [])} {tag.get('id') or ''} {tag.get('aria-label') or ''} {tag.get('title') or ''}".lower()


def _inline_svg_is_logo(svg: Tag, home_url: str) -> bool:
    """An inline SVG counts as the logo only with a positive signal and outside any button."""
    home = urlparse(home_url)
    linked_home = False
    named_logo = "logo" in _labels(svg) or "brand" in _labels(svg)
    depth = 0
    for parent in svg.parents:
        if not isinstance(parent, Tag) or parent.name in ("body", "html", "[document]"):
            break
        if parent.name == "button" or (parent.get("role") or "").lower() == "button":
            return False
        if parent.name == "a" and not linked_home:
            target = urlparse(urljoin(home_url, (parent.get("href") or "").strip()))
            linked_home = target.netloc == home.netloc and target.path.rstrip("/") in ("", home.path.rstrip("/")) and not target.query
        if depth < 3:
            words = _labels(parent)
            named_logo = named_logo or "logo" in words or "brand" in words
        depth += 1
    if not (linked_home or named_logo):
        return False
    tokens = set(re.split(r"[^a-z]+", _labels(svg)))
    return named_logo or not (tokens & _UI_ICON_WORDS)


_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_CSS_RULE_RE = re.compile(r"([^{};]{1,160})\{([^{}]{1,24000})\}")
_FONT_FACE_RE = re.compile(r"@font-face\s*\{([^{}]{1,4000})\}", re.I | re.S)
_CUSTOM_PROP_RE = re.compile(r"(--[a-zA-Z0-9_-]{2,64})\s*:\s*([^;}{]{1,220})")
_FONT_FAMILY_DECL_RE = re.compile(r"(?<![a-zA-Z-])font-family\s*:\s*([^;}{]{1,240})", re.I)
_HEX_COLOR_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_RGB_COLOR_RE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})(?:\s*[,/]\s*[\d.]+%?)?\s*\)",
    re.I,
)
_COLOR_VALUE_HINT_RE = re.compile(
    r"(#(?:[0-9a-fA-F]{3,8})\b|rgba?\([^)]+\)|hsla?\([^)]+\)|oklch\([^)]+\)|oklab\([^)]+\))",
    re.I,
)

_PRIORITY_SELECTORS = (
    ":root",
    "html",
    "body",
    "[data-theme",
    ".dark",
    ".light",
    "header",
    "nav",
    "main",
    "h1",
    "h2",
    "a",
    "button",
    ".btn",
    ".cta",
    ".hero",
)

_GENERIC_FONT_GENERICS = frozenset(
    {
        "sans-serif",
        "serif",
        "monospace",
        "system-ui",
        "-apple-system",
        "blinkmacsystemfont",
        "segoe ui",
        "roboto",
        "helvetica neue",
        "arial",
        "noto sans",
        "apple color emoji",
        "segoe ui emoji",
        "segoe ui symbol",
        "noto color emoji",
        "ui-sans-serif",
        "ui-serif",
        "ui-monospace",
        "cursive",
        "fantasy",
        "inherit",
        "initial",
        "unset",
    }
)

def _normalize_hex(hex_digits: str) -> Optional[str]:
    h = hex_digits.lower().strip()
    if len(h) == 3:
        return f"#{h[0]*2}{h[1]*2}{h[2]*2}"
    if len(h) == 4:
        return f"#{h[0]*2}{h[1]*2}{h[2]*2}"
    if len(h) == 6:
        return f"#{h}"
    if len(h) == 8:
        # Ignore fully transparent 8-digit hex
        if h[6:] == "00":
            return None
        return f"#{h[:6]}"
    return None


def _hex_saturation_and_luma(hex6: str) -> tuple[float, float]:
    r = int(hex6[1:3], 16) / 255.0
    g = int(hex6[3:5], 16) / 255.0
    b = int(hex6[5:7], 16) / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    sat = 0.0 if mx == 0 else (mx - mn) / mx
    return sat, luma


def _parse_google_fonts_families(href: str) -> list[str]:
    families: list[str] = []
    try:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        for raw_fam in qs.get("family", []):
            # Google Fonts CSS1 separates multiple families by "|"
            for chunk in raw_fam.split("|"):
                name = unquote(chunk.split(":", 1)[0]).replace("+", " ").strip()
                if name and name not in families:
                    families.append(name)
    except Exception:
        pass
    return families


def _clean_font_family_primary(font_stack: str) -> list[str]:
    out: list[str] = []
    for part in font_stack.split(","):
        cleaned = part.strip().strip("'\"").strip()
        if not cleaned or cleaned.startswith("var("):
            continue
        if cleaned.lower() in _GENERIC_FONT_GENERICS:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return out


def extract_observed_brand_kit(
    home_html: str,
    home_url: str,
    schema_blocks: Optional[list[dict]] = None,
    downloader=None,
    domain_folder: str = "",
    *,
    allow_url: Optional[Callable] = None,
    source_artifacts: Optional[dict] = None,
    site_root: Optional[str] = None,
) -> dict:
    """
    Deterministically extract observed brand design tokens, stylesheets, webfonts,
    font-family declarations, logos, and favicons from the homepage HTML and its
    linked CSS stylesheets. Never guesses visual colors without a CSS/HTML locator.
    """
    source_artifacts = source_artifacts if source_artifacts is not None else {}
    result = {
        "sources": [],
        "resourceDeclarations": [],
        "warnings": [],
        "humanApprovalRequired": True,
        "visuallyInspected": False,
        "limitations": ["Sampled declared CSS literals, not computed styles, media-query application or approved brand roles."],
        "stylesheetUrls": [],
        "logoUrls": [],
        "faviconUrls": [],
        "localLogoAsset": None,
        "localFaviconAsset": None,
        "themeColor": None,
        "colorTokens": [],
        "palette": [],
        "typography": {
            "webfonts": [],
            "fontFaces": [],
            "fontTokens": [],
            "fontStacks": [],
            "primaryFamilies": [],
        },
    }
    if not home_html:
        return result

    soup = BeautifulSoup(keep_trailing_content(home_html), _HTML_PARSER)

    # 1. Theme color meta
    for meta in soup.find_all("meta"):
        if (meta.get("name") or "").lower().strip() == "theme-color":
            tc = (meta.get("content") or "").strip()
            if tc:
                result["themeColor"] = tc
                break

    # 2. Discover stylesheets, webfonts, and icons from <link>
    css_urls: list[str] = []
    favicon_urls: list[str] = []
    webfonts: list[dict] = []

    for link in soup.find_all("link"):
        rel_raw = link.get("rel") or []
        rels = [str(r).lower() for r in (rel_raw.split() if isinstance(rel_raw, str) else rel_raw)]
        href = (link.get("href") or "").strip()
        if not href or href.startswith("data:"):
            continue
        full_u = urljoin(home_url, href)
        u_low = full_u.lower()

        if "icon" in rels or "apple-touch-icon" in rels or "shortcut" in rels:
            if full_u not in favicon_urls:
                favicon_urls.append(full_u)

        is_style = "stylesheet" in rels or (
            "preload" in rels and (link.get("as") or "").lower().strip() == "style"
        )
        if is_style:
            if "fonts.googleapis.com" in u_low:
                fams = _parse_google_fonts_families(full_u)
                for fam in fams:
                    if all(w["family"] != fam for w in webfonts):
                        webfonts.append({"family": fam, "provider": "Google Fonts", "source": full_u, "familyState": "declared-in-resource-url"})
            elif "use.typekit.net" in u_low:
                webfonts.append({"family": None, "provider": "Adobe Fonts", "source": full_u, "familyState": "not-observed"})
            elif "api.fontshare.com" in u_low:
                webfonts.append({"family": None, "provider": "Fontshare", "source": full_u, "familyState": "not-observed"})
            else:
                if full_u not in css_urls:
                    css_urls.append(full_u)

    result["stylesheetUrls"] = css_urls[:12]

    # 3. Discover Brand Logos (JSON-LD Organization/Brand logo + Header/Nav img or inline SVG)
    logo_urls: list[str] = []
    inline_logo_svg: Optional[str] = None

    for blk in schema_blocks or []:
        if not isinstance(blk, dict):
            continue
        logo_field = blk.get("logo")
        cand = ""
        if isinstance(logo_field, str):
            cand = logo_field.strip()
        elif isinstance(logo_field, dict) and isinstance(logo_field.get("url"), str):
            cand = logo_field["url"].strip()
        if cand and cand.startswith(("http://", "https://", "/")):
            full_logo = urljoin(home_url, cand)
            if full_logo not in logo_urls:
                logo_urls.append(full_logo)

    # Search header / nav / logo containers for <img> or <svg>
    logo_containers: list[Tag] = []
    for sel_tag in soup.find_all(["header", "nav"]):
        if isinstance(sel_tag, Tag):
            logo_containers.append(sel_tag)
    for attr_tag in soup.find_all(["a", "div", "span"]):
        if not isinstance(attr_tag, Tag):
            continue
        cls_id = f"{' '.join(attr_tag.get('class') or [])} {attr_tag.get('id') or ''} {attr_tag.get('aria-label') or ''}".lower()
        if "logo" in cls_id or "brand" in cls_id:
            logo_containers.append(attr_tag)

    for container in logo_containers[:12]:
        for img in container.find_all("img", limit=4):
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            full_img = urljoin(home_url, src)
            alt_cls = f"{img.get('alt') or ''} {' '.join(img.get('class') or [])} {src}".lower()
            if "logo" in alt_cls or "brand" in alt_cls or container.name in ("header", "nav"):
                if full_img not in logo_urls:
                    logo_urls.append(full_img)
        if inline_logo_svg is None:
            for svg in container.find_all("svg", limit=8):
                if not isinstance(svg, Tag) or not _inline_svg_is_logo(svg, home_url):
                    continue
                raw_svg = _restore_svg_case(str(svg))
                if 80 <= len(raw_svg) <= 120_000:
                    if "xmlns=" not in raw_svg[:180]:
                        raw_svg = raw_svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
                    inline_logo_svg = raw_svg
                    break

    result["logoUrls"] = logo_urls[:8]
    result["faviconUrls"] = favicon_urls[:6]

    # 4. Collect CSS sources: inline <style> blocks + up to 5 external stylesheets (sequentially for DNS lock safety)
    css_sources: list[tuple[str, str]] = []
    for idx, st_tag in enumerate(soup.find_all("style")[:10]):
        st_txt = st_tag.string or st_tag.get_text() or ""
        if st_txt.strip():
            css_sources.append((f"{home_url}#inline-style-{idx + 1}", st_txt[:250_000]))

    def permitted(url):
        if allow_url is None:
            return True
        decision = allow_url(url)
        return decision.get("allowed") is True if isinstance(decision, dict) else decision is True

    # Retained homepage bytes support inline declarations, without fabricating a
    # raw HTTP receipt from decoded text. Caller-supplied artifacts take priority.
    if home_url not in source_artifacts and site_root:
        data = home_html.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        relative = f"_raw/brand-home-{digest}.html"
        destination = Path(site_root) / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        source_artifacts[home_url] = {"rawPath": relative, "rawSha256": digest, "rawKind": "supplied-html"}

    for css_u in css_urls[:5]:
        target = css_u
        try:
            for _hop in range(5):
                if not permitted(target):
                    result["warnings"].append(f"Stylesheet excluded by policy: {target}")
                    break
                validate_url_strict(target)
                with safe_requests_session(target) as session:
                    resp = session.get(target, headers={**DEFAULT_REQUEST_HEADERS, "Accept": "text/css,*/*;q=0.1"},
                                       timeout=4.0, stream=True, allow_redirects=False)
                    try:
                        if 300 <= resp.status_code < 400:
                            location = resp.headers.get("Location")
                            if not location:
                                break
                            target = urljoin(target, location)
                            continue
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if resp.status_code != 200 or "text/html" in ctype:
                            result["warnings"].append(f"Stylesheet did not return CSS content: {target}")
                            break
                        chunks, size = [], 0
                        for chunk in resp.iter_content(chunk_size=65536):
                            size += len(chunk)
                            if size > 512 * 1024:
                                raise ValueError("Stylesheet exceeded 512 KB limit")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        css_txt = decode_body(raw, ctype)
                        if not css_txt.strip() or css_txt.lstrip().startswith("<"):
                            break
                        digest = hashlib.sha256(raw).hexdigest()
                        record = {"url": css_u, "finalUrl": target, "rawSha256": digest,
                                  "rawKind": "http-response-decoded", "statusCode": 200,
                                  "resourcePolicy": "allowed-by-caller" if allow_url is not None else "not-checked"}
                        if site_root:
                            relative = f"_raw/brand-{digest}.css"
                            destination = Path(site_root) / relative
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(raw)
                            record["rawPath"] = relative
                            try:
                                raw_text = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                raw_text = None
                            if raw_text != css_txt:
                                text_data = css_txt.encode("utf-8")
                                text_digest = hashlib.sha256(text_data).hexdigest()
                                text_relative = f"_raw/brand-{text_digest}.utf8.css"
                                (Path(site_root) / text_relative).write_bytes(text_data)
                                record.update(textPath=text_relative, textSha256=text_digest)
                        else:
                            record["text"] = css_txt
                        source_artifacts[css_u] = record
                        result["sources"].append(record)
                        css_sources.append((css_u, css_txt))
                        break
                    finally:
                        resp.close()
            else:
                result["warnings"].append(f"Stylesheet redirect limit reached: {css_u}")
        except (URLSafetyError, Exception) as exc:
            result["warnings"].append(f"Stylesheet unavailable: {css_u}: {type(exc).__name__}")

    result["cssCoverage"] = {"discovered": len(css_urls), "selected": min(5, len(css_urls)),
                             "fetched": len(result["sources"]), "limit": 5}
    if len(css_urls) > 5:
        result["warnings"].append(f"Stylesheet sample limit left {len(css_urls) - 5} links unselected.")

    # 5. Parse CSS custom properties, @font-face, font-family stacks, and hex/RGB colors with locators
    color_tokens: list[dict] = []
    seen_color_tokens: set[tuple[str, str]] = set()
    font_tokens: list[dict] = []
    seen_font_tokens: set[tuple[str, str]] = set()
    font_faces: list[dict] = []
    seen_font_faces: set[str] = set()
    font_stacks: list[dict] = []
    seen_font_stacks: set[tuple[str, str]] = set()

    # hex6 -> {hex, raw, count, priority, selector, source}
    color_tally: dict[str, dict] = {}

    if result["themeColor"]:
        m_hex = _HEX_COLOR_RE.search(result["themeColor"])
        if m_hex:
            norm = _normalize_hex(m_hex.group(1))
            if norm:
                color_tally[norm] = {
                    "hex": norm,
                    "declared": result["themeColor"],
                    "count": 1,
                    "priority": 3,
                    "selector": 'meta[name="theme-color"]',
                    "source": home_url,
                }

    for source_loc, raw_css in css_sources:
        clean_css = _CSS_COMMENT_RE.sub(" ", raw_css)

        for ff_match in _FONT_FACE_RE.finditer(clean_css):
            ff_body = ff_match.group(1)
            fam_m = _FONT_FAMILY_DECL_RE.search(ff_body)
            if fam_m:
                for fam_name in _clean_font_family_primary(fam_m.group(1)):
                    if fam_name.lower() not in seen_font_faces and len(font_faces) < 16:
                        seen_font_faces.add(fam_name.lower())
                        font_faces.append({"family": fam_name, "source": source_loc, "selector": "@font-face", "quote": fam_m.group(0)})

        for rule_m in _CSS_RULE_RE.finditer(clean_css):
            selector = re.sub(r"\s+", " ", rule_m.group(1)).strip()
            body = rule_m.group(2)
            if not selector or selector.startswith("@keyframes") or selector.startswith("@media"):
                continue
            sel_low = selector.lower()
            is_priority_sel = any(sel_low == p or sel_low.startswith(p) for p in _PRIORITY_SELECTORS)

            # Custom properties (--*)
            for cp_m in _CUSTOM_PROP_RE.finditer(body):
                prop_name = cp_m.group(1).strip()
                prop_val = re.sub(r"\s+", " ", cp_m.group(2)).strip()
                p_low = prop_name.lower()

                if _COLOR_VALUE_HINT_RE.search(prop_val) and not any(
                    skip in p_low for skip in ("--tw-ring", "--tw-shadow", "--wp--preset--gradient")
                ):
                    if (prop_name, prop_val) not in seen_color_tokens and len(color_tokens) < 28:
                        seen_color_tokens.add((prop_name, prop_val))
                        color_tokens.append(
                            {
                                "token": prop_name,
                                "value": prop_val,
                                "selector": selector[:80],
                                "source": source_loc,
                                "quote": cp_m.group(0),
                            }
                        )

                if "font" in p_low and not any(
                    sz in p_low for sz in ("size", "weight", "style", "feature", "variation")
                ):
                    if (prop_name, prop_val) not in seen_font_tokens and len(font_tokens) < 16:
                        seen_font_tokens.add((prop_name, prop_val))
                        font_tokens.append(
                            {
                                "token": prop_name,
                                "value": prop_val,
                                "selector": selector[:80],
                                "source": source_loc,
                                "quote": cp_m.group(0),
                            }
                        )

            # Explicit font-family stacks on semantic selectors
            if any(
                tok in sel_low
                for tok in (":root", "html", "body", "h1", "h2", "h3", "code", "pre", "heading", "title")
            ):
                for fd_m in _FONT_FAMILY_DECL_RE.finditer(body):
                    f_val = re.sub(r"\s+", " ", fd_m.group(1)).strip()
                    short_sel = selector[:64]
                    if (short_sel, f_val) not in seen_font_stacks and len(font_stacks) < 16:
                        seen_font_stacks.add((short_sel, f_val))
                        font_stacks.append(
                            {
                                "selector": short_sel,
                                "fontFamily": f_val,
                                "source": source_loc,
                                "quote": fd_m.group(0),
                            }
                        )

            # Declared Hex & RGB colors
            for hx_m in _HEX_COLOR_RE.finditer(body):
                norm_h = _normalize_hex(hx_m.group(1))
                if not norm_h:
                    continue
                entry = color_tally.get(norm_h)
                prio = 2 if is_priority_sel else 1
                if entry is None:
                    color_tally[norm_h] = {
                        "hex": norm_h,
                        "declared": hx_m.group(0),
                        "count": 1,
                        "priority": prio,
                        "selector": selector[:72],
                        "source": source_loc,
                    }
                else:
                    entry["count"] += 1
                    if prio > entry["priority"]:
                        entry["priority"] = prio
                        entry["selector"] = selector[:72]
                        entry["source"] = source_loc

            for rgb_m in _RGB_COLOR_RE.finditer(body):
                r_i, g_i, b_i = (
                    min(255, int(rgb_m.group(1))),
                    min(255, int(rgb_m.group(2))),
                    min(255, int(rgb_m.group(3))),
                )
                norm_h = f"#{r_i:02x}{g_i:02x}{b_i:02x}"
                prio = 2 if is_priority_sel else 1
                entry = color_tally.get(norm_h)
                if entry is None:
                    color_tally[norm_h] = {
                        "hex": norm_h,
                        "declared": rgb_m.group(0),
                        "count": 1,
                        "priority": prio,
                        "selector": selector[:72],
                        "source": source_loc,
                    }
                else:
                    entry["count"] += 1
                    if prio > entry["priority"]:
                        entry["priority"] = prio
                        entry["selector"] = selector[:72]
                        entry["source"] = source_loc

    # Rank palette: surface chromatic brand colors first, followed by top background/ink neutrals
    ranked_colors = []
    for item in color_tally.values():
        sat, luma = _hex_saturation_and_luma(item["hex"])
        is_vivid = sat >= 0.22 and 0.06 <= luma <= 0.94
        candidate = "chromatic" if is_vivid else ("dark-neutral" if luma < 0.22 else ("light-neutral" if luma > 0.85 else "neutral"))
        score = (100 if is_vivid else 0) + item["priority"] * 25 + min(40, item["count"])
        ranked_colors.append({**item, "role": "unassigned", "candidateRole": candidate, "_score": score})

    ranked_colors.sort(key=lambda c: (-c["_score"], -c["count"], c["hex"]))
    palette_out = []
    for c in ranked_colors[:12]:
        palette_out.append(
            {
                "hex": c["hex"],
                "declared": c["declared"],
                "role": c["role"],
                "candidateRole": c["candidateRole"],
                "roleEvidence": "inferred from saturation and luminance, not observed brand use",
                "confidence": "low",
                "quote": c["declared"],
                "occurrences": c["count"],
                "selector": c["selector"],
                "source": c["source"],
            }
        )

    # Consolidate primary human-readable font families across webfonts, @font-face, fontTokens, and fontStacks
    primary_fams: list[str] = []
    for wf in webfonts:
        if wf["family"] and wf["family"] not in primary_fams:
            primary_fams.append(wf["family"])
    for ff in font_faces:
        if ff["family"] not in primary_fams:
            primary_fams.append(ff["family"])
    for ft in font_tokens:
        for nm in _clean_font_family_primary(ft["value"]):
            if nm not in primary_fams:
                primary_fams.append(nm)
    for fs_item in font_stacks:
        for nm in _clean_font_family_primary(fs_item["fontFamily"]):
            if nm not in primary_fams:
                primary_fams.append(nm)

    # 6. Save primary brand logo & favicon locally into assets/ when downloader is active
    if downloader is not None and domain_folder:
        for l_url in logo_urls[:2]:
            if not permitted(l_url):
                continue
            fname = downloader.download_image(l_url)
            if fname:
                result["localLogoAsset"] = f"sites/{domain_folder}/assets/{fname}"
                break
        if result["localLogoAsset"] is None and inline_logo_svg is not None:
            fname = downloader.save_inline_svg(
                f"inline-svg://{domain_folder}/brand-logo",
                "brand-logo.svg",
                inline_logo_svg,
            )
            if fname:
                result["localLogoAsset"] = f"sites/{domain_folder}/assets/{fname}"

        for f_url in favicon_urls[:2]:
            if not permitted(f_url):
                continue
            fname = downloader.download_image(f_url)
            if fname:
                result["localFaviconAsset"] = f"sites/{domain_folder}/assets/{fname}"
                break

    declared_css = set(css_urls) | {font["source"] for font in webfonts}
    for match in re.finditer(r"<(?:link|img)\b[^>]*>", home_html, re.I):
        element = BeautifulSoup(match.group(0), _HTML_PARSER).find(["link", "img"])
        if element is None:
            continue
        reference = element.get("href") or element.get("src")
        if not isinstance(reference, str):
            continue
        resolved = urljoin(home_url, reference)
        kind = ("stylesheet" if resolved in declared_css else "logo-candidate" if resolved in logo_urls
                else "favicon" if resolved in favicon_urls else None)
        if kind:
            result["resourceDeclarations"].append({"kind": kind, "url": resolved,
                                                   "quote": match.group(0), "source": home_url})

    # Attach retained-byte references to observations. Inline style locators map
    # to the exact retained homepage artifact supplied by the caller.
    for item in color_tokens + palette_out + font_tokens + font_faces + font_stacks + result["resourceDeclarations"]:
        source = item.get("source", "")
        artifact = source_artifacts.get(source.split("#inline-style-", 1)[0]) or {}
        if artifact.get("textPath"):
            item.update(rawPath=artifact["textPath"], rawSha256=artifact["textSha256"], rawKind="decoded-text",
                        parentRawPath=artifact.get("rawPath"), parentRawSha256=artifact.get("rawSha256"))
        else:
            for key in ("rawPath", "rawSha256", "rawKind", "parentRawPath", "parentRawSha256"):
                if artifact.get(key):
                    item[key] = artifact[key]
    result["sourceArtifacts"] = dict(source_artifacts)
    result["colorTokens"] = color_tokens
    result["palette"] = palette_out
    result["typography"] = {
        "webfonts": webfonts,
        "fontFaces": font_faces,
        "fontTokens": font_tokens,
        "fontStacks": font_stacks,
        "primaryFamilies": primary_fams[:10],
    }
    return result
