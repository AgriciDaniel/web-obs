"""Deterministic per-page document checks computed from one captured HTML response.

Every value here is an observation of the saved HTML and response headers. Nothing is
requested from the network. Thresholds follow common crawler conventions and are
labelled as heuristics where they are not part of a specification.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Optional
from urllib.parse import urlparse

try:
    from bs4 import Tag
except ImportError:  # pragma: no cover - bs4 is a required engine package
    Tag = None

try:
    import html5lib  # optional
except ImportError:
    html5lib = None

try:
    from spellchecker import SpellChecker  # optional, pyspellchecker
except ImportError:
    SpellChecker = None

# Optional features the coordinator can switch on for one capture.
_SETTINGS = {"spell_check": False, "html_validation": True}
_SPELLER = None
# html5lib is pure Python. Cap its total time per capture so large sites stay fast.
_VALIDATION_BUDGET_SEC = 60.0
_validation_spent = 0.0


def configure(*, spell_check: Optional[bool] = None, html_validation: Optional[bool] = None) -> None:
    global _validation_spent
    _validation_spent = 0.0
    if spell_check is not None:
        _SETTINGS["spell_check"] = bool(spell_check)
    if html_validation is not None:
        _SETTINGS["html_validation"] = bool(html_validation)


def optional_feature_states() -> dict:
    return {
        "htmlValidation": {"state": "ok" if html5lib is not None and _SETTINGS["html_validation"] else "skipped",
                           "detail": "html5lib parse errors" if html5lib is not None else "Install html5lib to enable HTML validation."},
        "spellCheck": {"state": "ok" if SpellChecker is not None and _SETTINGS["spell_check"] else "skipped",
                       "detail": ("English dictionary, opt-in" if _SETTINGS["spell_check"] else "Off by default. Enable it in settings.")
                       if SpellChecker is not None else "Install pyspellchecker to enable spell checking."},
    }


STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further get got had has have having he her here hers
herself him himself his how i if in into is it its itself just let me more most my myself no nor not now of off on once
only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves
then there these they this those through to too under until up us very was we were what when where which while who whom
why will with would you your yours yourself yourselves new one two use using used like make made way may might must
need via per yet etc www http https com
""".split())

DEPRECATED_TAGS = ("acronym", "applet", "basefont", "big", "blink", "center", "dir", "font", "frame", "frameset",
                   "isindex", "marquee", "nobr", "noframes", "spacer", "strike", "tt")
_LOREM_RE = re.compile(r"\blorem ipsum\b|\bdolor sit amet\b", re.I)
_WORD_RE = re.compile(r"[^\W\d_][\w'-]*", re.UNICODE)
_SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)")
_QUESTION_START_RE = re.compile(r"^(what|how|why|when|where|which|who|can|does|do|is|are|should|will)\b", re.I)
_UTF8_ALIASES = {"utf8": "utf-8", "utf-8": "utf-8", "unicode-1-1-utf-8": "utf-8"}
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|msclkid$|mc_)", re.I)

# Lighthouse DOM size guidance.
DOM_NODE_LIMIT = 1500
DOM_DEPTH_LIMIT = 32
DOM_CHILDREN_LIMIT = 60


def tokenize(text) -> list[str]:
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text if isinstance(t, (str, int, float)))
    elif not isinstance(text, str):
        text = "" if text is None or isinstance(text, (dict, bool)) else str(text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return [w.lower().strip("'-") for w in _WORD_RE.findall(text or "") if w.strip("'-")]


def significant_terms(text: str) -> list[str]:
    return [t for t in tokenize(text) if len(t) >= 3 and t not in STOPWORDS]


def _syllables(word: str) -> int:
    word = word.lower()
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    groups = re.findall(r"[aeiouy]{1,2}", word)
    return max(1, len(groups))


def readability(text: str, lang: str = "") -> Optional[dict]:
    """English readability formulas. Returns None for short or non-English text."""
    if lang and not lang.lower().startswith("en"):
        return None
    words = _WORD_RE.findall(text or "")
    if len(words) < 100:
        return None
    sentences = max(1, len(_SENTENCE_RE.findall(text)))
    letters = sum(sum(ch.isalpha() for ch in w) for w in words)
    syllables = sum(_syllables(w) for w in words)
    polysyllables = sum(1 for w in words if _syllables(w) >= 3)
    n = len(words)
    wps = n / sentences
    spw = syllables / n
    return {
        "fleschReadingEase": round(206.835 - 1.015 * wps - 84.6 * spw, 1),
        "fleschKincaidGrade": round(0.39 * wps + 11.8 * spw - 15.59, 1),
        "automatedReadabilityIndex": round(4.71 * (letters / n) + 0.5 * wps - 21.43, 1),
        "colemanLiauIndex": round(0.0588 * (letters / n * 100) - 0.296 * (sentences / n * 100) - 15.8, 1),
        "smogIndex": round(1.043 * ((polysyllables * (30 / sentences)) ** 0.5) + 3.1291, 1) if sentences >= 3 else None,
        "sentences": sentences,
        "wordsPerSentence": round(wps, 1),
        "note": "English formulas with a heuristic syllable count.",
    }


def simhash64(text: str) -> str:
    """64-bit SimHash over word 3-shingles, as 16 hex characters. Empty text gives an empty string."""
    tokens = tokenize(text)
    if len(tokens) < 3:
        return ""
    weights = [0] * 64
    for shingle, count in Counter(" ".join(tokens[i:i + 3]) for i in range(len(tokens) - 2)).items():
        h = int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += count if (h >> bit) & 1 else -count
    value = 0
    for bit in range(64):
        if weights[bit] > 0:
            value |= 1 << bit
    return f"{value:016x}"


def simhash_distance(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def keyword_density(text: str, top: int = 8) -> dict:
    tokens = tokenize(text)
    total = len(tokens)
    if total < 30:
        return {"totalWords": total, "unigrams": [], "bigrams": [], "trigrams": []}

    def ngrams(n: int):
        counts: Counter = Counter()
        for i in range(total - n + 1):
            gram = tokens[i:i + n]
            if gram[0] in STOPWORDS or gram[-1] in STOPWORDS or any(len(g) < 2 for g in gram):
                continue
            if n == 1 and len(gram[0]) < 3:
                continue
            counts[" ".join(gram)] += 1
        return [{"term": term, "count": count, "density": round(count * n / total * 100, 2)}
                for term, count in counts.most_common(top) if count >= 2]

    return {"totalWords": total, "unigrams": ngrams(1), "bigrams": ngrams(2), "trigrams": ngrams(3)}


def _dom_stats(soup) -> dict:
    root = soup.find("html") or soup
    nodes = 0
    max_depth = 0
    max_children = 0
    widest = ""
    stack = [(root, 1)]
    while stack:
        el, depth = stack.pop()
        nodes += 1
        if depth > max_depth:
            max_depth = depth
        children = [c for c in el.children if isinstance(c, Tag)]
        if len(children) > max_children:
            max_children = len(children)
            widest = el.name or ""
        stack.extend((c, depth + 1) for c in children)
    return {"nodes": nodes, "maxDepth": max_depth, "maxChildren": max_children, "widestElement": widest}


def _relevance(source: str, body_terms: set[str]) -> Optional[float]:
    terms = set(significant_terms(source))
    if not terms:
        return None
    return round(len(terms & body_terms) / len(terms), 2)


def _charset_of(content_type: str) -> str:
    m = re.search(r"charset\s*=\s*['\"]?([^;,'\"\s]+)", content_type or "", re.I)
    return _norm_charset(m.group(1)) if m else ""


def _norm_charset(value: str) -> str:
    v = (value or "").strip().lower()
    return _UTF8_ALIASES.get(v, v)


def _url_checks(page_url: str) -> tuple[dict, list[str]]:
    parsed = urlparse(page_url)
    path = parsed.path or "/"
    issues = []
    params = [p.split("=", 1)[0] for p in parsed.query.split("&") if p]
    info = {"length": len(page_url), "pathLength": len(path), "queryParams": params,
            "hasUppercase": path != path.lower(), "hasUnderscore": "_" in path,
            "nonAscii": any(ord(ch) > 127 for ch in page_url), "doubleSlash": "//" in path}
    if len(page_url) > 115:
        issues.append("url-too-long")
    if params and not all(_TRACKING_PARAMS.match(p) for p in params):
        issues.append("url-has-parameters")
    if info["hasUppercase"]:
        issues.append("url-uppercase")
    if info["hasUnderscore"]:
        issues.append("url-underscores")
    if info["nonAscii"]:
        issues.append("url-non-ascii")
    if info["doubleSlash"]:
        issues.append("url-double-slash")
    return info, issues


def _cache_info(headers: dict) -> dict:
    cc = headers.get("cache-control", "")
    directives = {}
    for part in cc.split(","):
        part = part.strip().lower()
        if not part:
            continue
        key, _, value = part.partition("=")
        directives[key.strip()] = value.strip().strip('"')

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    max_age = _int(directives.get("s-maxage")) if "s-maxage" in directives else _int(directives.get("max-age"))
    cacheable = not ({"no-store", "private"} & set(directives))
    return {"cacheControl": cc or None, "maxAge": max_age, "cacheable": cacheable,
            "noStore": "no-store" in directives, "noCache": "no-cache" in directives,
            "etag": bool(headers.get("etag")), "lastModified": headers.get("last-modified") or None,
            "contentEncoding": headers.get("content-encoding") or None}


def _a11y_static(soup) -> dict:
    labelled_ids = {str(lbl.get("for")) for lbl in soup.find_all("label") if lbl.get("for")}
    unlabeled_inputs = 0
    for inp in soup.find_all(["input", "select", "textarea"]):
        itype = (inp.get("type") or "text").lower()
        if itype in ("hidden", "submit", "button", "reset", "image"):
            continue
        if inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title"):
            continue
        if inp.get("id") and str(inp.get("id")) in labelled_ids:
            continue
        if inp.find_parent("label") is not None:
            continue
        unlabeled_inputs += 1
    unnamed_buttons = 0
    for btn in soup.find_all("button"):
        if btn.get_text(strip=True) or btn.get("aria-label") or btn.get("aria-labelledby") or btn.get("title"):
            continue
        if any((img.get("alt") or "").strip() for img in btn.find_all("img")):
            continue
        unnamed_buttons += 1
    empty_links = 0
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) or a.get("aria-label") or a.get("aria-labelledby") or a.get("title"):
            continue
        if any((img.get("alt") or "").strip() for img in a.find_all("img")):
            continue
        if a.find("svg") is not None and a.find("svg").find("title") is not None:
            continue
        empty_links += 1
    return {"unlabeledInputs": unlabeled_inputs, "unnamedButtons": unnamed_buttons, "emptyLinks": empty_links,
            "note": "Static HTML checks only. Not a full accessibility assessment."}


def _citability(soup, h1_text: str) -> dict:
    scope = soup.find("main") or soup.find("article") or soup.body or soup
    headings = [re.sub(r"\s+", " ", h.get_text(" ", strip=True)) for h in scope.find_all(["h2", "h3"])]
    question_headings = sum(1 for h in headings if h.endswith("?") or _QUESTION_START_RE.match(h))
    paragraphs = [re.sub(r"\s+", " ", p.get_text(" ", strip=True)) for p in scope.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) >= 20]
    para_words = [len(p.split()) for p in paragraphs]
    first = paragraphs[0] if paragraphs else ""
    faq_blocks = len(scope.find_all("details")) + len(scope.find_all(attrs={"itemtype": re.compile("FAQPage|Question", re.I)}))
    return {
        "questionHeadings": question_headings,
        "headingsChecked": len(headings),
        "lists": len(scope.find_all(["ul", "ol"])),
        "tables": len(scope.find_all("table")),
        "faqBlocks": faq_blocks,
        "paragraphs": len(paragraphs),
        "avgParagraphWords": round(sum(para_words) / len(para_words), 1) if para_words else 0,
        "longParagraphs": sum(1 for w in para_words if w > 150),
        "answerFirst": bool(first) and 15 <= len(first.split()) <= 80,
        "note": "Heuristic structure signals that tend to make passages easy to quote. Not a score.",
    }


def _validation_errors(html: str) -> Optional[dict]:
    global _validation_spent
    if html5lib is None or not _SETTINGS["html_validation"] or len(html) > 1_500_000:
        return None
    if _validation_spent >= _VALIDATION_BUDGET_SEC:
        return {"errors": None, "topCodes": [], "validator": "html5lib parse errors",
                "skipped": f"The {int(_VALIDATION_BUDGET_SEC)} second validation budget for this capture was used up."}
    import time as _time
    started = _time.monotonic()
    try:
        parser = html5lib.HTMLParser(strict=False)
        parser.parse(html)
        errors = parser.errors
    except Exception:
        return None
    finally:
        _validation_spent += _time.monotonic() - started
    counts = Counter(str(code) for _pos, code, _vars in errors)
    return {"errors": len(errors), "topCodes": [{"code": c, "count": n} for c, n in counts.most_common(5)],
            "validator": "html5lib parse errors"}


# Scripts written without spaces between words: Han, Hiragana, Katakana, Thai, Lao, Myanmar and Khmer.
# Korean (Hangul) does use spaces, so it is counted normally.
_UNSPACED_SCRIPT = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff]")
_UNSPACED_LANGS = ("zh", "ja", "th", "lo", "km", "my")
# Googlebot reads the first 2 MB of an HTML file for Google Search, measured before compression.
GOOGLEBOT_HTML_LIMIT_BYTES = 2_000_000


def words_measurable(text: str, lang: str = "") -> bool:
    """Whether a whitespace word count means anything for this text.

    Chinese, Japanese, Thai, Lao, Khmer and Burmese do not put spaces between words, so splitting on
    spaces finds a handful of "words" in a long article. For those, word-based checks are not measured.
    """
    if (lang or "").lower().split("-")[0] in _UNSPACED_LANGS:
        return False
    letters = sum(1 for ch in text if ch.isalpha())
    return not letters or len(_UNSPACED_SCRIPT.findall(text)) / letters < 0.3


def _spelling(text: str, lang: str) -> Optional[dict]:
    global _SPELLER
    if SpellChecker is None or not _SETTINGS["spell_check"]:
        return None
    if not lang:  # an undeclared language is not evidence of English; missing-lang already reports it
        return {"checkedWords": 0, "possibleMisspellings": [], "note": "Spell check skipped: the page does not declare its language."}
    if not lang.lower().startswith("en"):
        return None
    if _SPELLER is None:
        _SPELLER = SpellChecker(language="en")
    words = [w for w in tokenize(text) if w.isalpha() and 3 <= len(w) <= 20]
    unknown = _SPELLER.unknown(set(words)) if words else set()
    counts = Counter(w for w in words if w in unknown)
    # Repeated unknown words are usually product names or jargon, not typos.
    likely = sorted(w for w, c in counts.items() if c == 1)[:25]
    return {"checkedWords": len(set(words)), "possibleMisspellings": likely,
            "note": "English dictionary. Names and jargon appear here too."}


def run_page_checks(*, html: str, soup, page_url: str, headers: dict, lang: str, title: str,
                    meta_description: str, visible_text: str, h1: list[str], meta_tags: list[tuple[str, str, str]],
                    canonical: str, images: list[dict], internal_links: list[dict], external_links: list[dict]) -> dict:
    """Return {"checks": {...}, "issues": [...], "simhash": str, "keywords": {...}}.

    `meta_tags` is a list of (name_lower, property_lower, content) for every <meta>.
    `headers` keys must be lower case.
    """
    issues: list[str] = []
    raw_bytes = len(html.encode("utf-8", errors="replace"))
    is_https = page_url.lower().startswith("https://")

    # Content volume and ratio
    text_chars = len(visible_text)
    text_ratio = round(text_chars / raw_bytes, 4) if raw_bytes else 0.0
    word_total = len(visible_text.split())
    measurable = words_measurable(visible_text, lang)
    if raw_bytes > 2048 and text_ratio < 0.10:
        issues.append("low-text-ratio")
    if measurable and word_total < 200:
        issues.append("thin-content")

    # Relevance of title and description to the body
    body_terms = set(significant_terms(visible_text))
    title_rel = _relevance(title, body_terms)
    desc_rel = _relevance(meta_description, body_terms)
    if measurable and title_rel is not None and title_rel < 0.3 and word_total >= 50:
        issues.append("title-not-reflected-in-content")
    if measurable and desc_rel is not None and desc_rel < 0.2 and word_total >= 50:
        issues.append("description-not-reflected-in-content")
    has_title_tag = bool(soup.title and soup.title.get_text(strip=True))
    # Twenty characters is a few English words but a full title in Chinese or Japanese.
    if has_title_tag and len(title) < 20 and words_measurable(title, lang):
        issues.append("title-too-short")

    # Document hygiene
    head_text = re.sub(r"^﻿", "", html.lstrip())
    head_text = re.sub(r"^(?:<!--.*?-->\s*)+", "", head_text, flags=re.S)
    has_doctype = head_text[:15].lower().startswith("<!doctype html")
    if not has_doctype:
        issues.append("missing-doctype")
    meta_charset = ""
    for m in soup.find_all("meta"):
        if m.get("charset"):
            meta_charset = _norm_charset(str(m.get("charset")))
            break
        if (m.get("http-equiv") or "").lower() == "content-type":
            meta_charset = _charset_of(str(m.get("content") or ""))
            if meta_charset:
                break
    header_charset = _charset_of(headers.get("content-type", ""))
    if not meta_charset and not header_charset:
        issues.append("missing-charset")
    charset_mismatch = bool(meta_charset and header_charset and meta_charset != header_charset)
    if charset_mismatch:
        issues.append("charset-mismatch")

    name_counts = Counter(name for name, _prop, _c in meta_tags if name)
    prop_counts = Counter(prop for _name, prop, _c in meta_tags if prop)
    duplicates = sorted([n for n in ("description", "robots", "viewport", "title") if name_counts.get(n, 0) > 1] +
                        [p for p in ("og:title", "og:description", "og:url", "og:image") if prop_counts.get(p, 0) > 1])
    canonical_count = sum(1 for link in soup.find_all("link")
                          if "canonical" in [str(r).lower() for r in (link.get("rel") or [])])
    title_count = len(soup.find_all("title"))
    if canonical_count > 1:
        duplicates.append("canonical")
    if title_count > 1:
        duplicates.append("title-tag")
    if duplicates:
        issues.append(f"duplicate-meta-tags ({len(duplicates)})")
    meta_refresh = ""
    for m in soup.find_all("meta"):
        if (m.get("http-equiv") or "").lower() == "refresh":
            meta_refresh = str(m.get("content") or "")
            break
    if meta_refresh and "url=" in meta_refresh.lower():
        issues.append("meta-refresh-redirect")
    deprecated = sorted({t.name for t in soup.find_all(DEPRECATED_TAGS)})
    if deprecated:
        issues.append(f"deprecated-html-tags ({len(deprecated)})")
    has_frames = bool(soup.find(["frameset", "frame"]))
    has_flash = any(".swf" in str(el.get("src") or el.get("data") or "").lower()
                    or "shockwave" in str(el.get("type") or "").lower()
                    for el in soup.find_all(["embed", "object"]))
    if has_frames:
        issues.append("uses-frames")
    if has_flash:
        issues.append("uses-flash")
    lorem = bool(_LOREM_RE.search(visible_text))
    if lorem:
        issues.append("placeholder-text")
    if raw_bytes > GOOGLEBOT_HTML_LIMIT_BYTES:
        issues.append("html-over-2mb")
    if not lang:
        issues.append("missing-lang")

    # Mixed content and insecure links
    insecure_links = []
    mixed_resources = []
    if is_https:
        for link in list(internal_links) + list(external_links):
            if str(link.get("url", "")).lower().startswith("http://"):
                insecure_links.append(link["url"])
        for tag, attr in (("img", "src"), ("script", "src"), ("iframe", "src"), ("source", "src"),
                          ("video", "src"), ("audio", "src"), ("embed", "src")):
            for el in soup.find_all(tag):
                val = str(el.get(attr) or "")
                if val.lower().startswith("http://"):
                    mixed_resources.append(val)
        for link in soup.find_all("link", href=True):
            rels = [str(r).lower() for r in (link.get("rel") or [])]
            if ("stylesheet" in rels or "preload" in rels) and str(link.get("href")).lower().startswith("http://"):
                mixed_resources.append(str(link.get("href")))
    if insecure_links:
        issues.append(f"links-to-http ({len(insecure_links)})")
    if mixed_resources:
        issues.append(f"mixed-content ({len(mixed_resources)})")

    # Scripts, stylesheets, render blocking
    head = soup.find("head")
    scripts = soup.find_all("script")
    external_scripts = [s for s in scripts if s.get("src")]
    stylesheets = [link for link in soup.find_all("link", href=True)
                   if "stylesheet" in [str(r).lower() for r in (link.get("rel") or [])]]
    blocking_scripts = []
    blocking_styles = []
    if head is not None:
        for s in head.find_all("script", src=True):
            stype = (s.get("type") or "").lower()
            if s.has_attr("async") or s.has_attr("defer") or stype == "module" or (stype and "javascript" not in stype):
                continue
            blocking_scripts.append(str(s.get("src")))
        for link in head.find_all("link", href=True):
            if "stylesheet" not in [str(r).lower() for r in (link.get("rel") or [])]:
                continue
            media = (link.get("media") or "all").lower()
            if link.has_attr("disabled") or media in ("print", "none") or "onload" in link.attrs:
                continue
            blocking_styles.append(str(link.get("href")))
    if len(blocking_scripts) + len(blocking_styles) > 0:
        issues.append(f"render-blocking-resources ({len(blocking_scripts) + len(blocking_styles)})")

    # DOM complexity
    dom = _dom_stats(soup)
    if dom["nodes"] > DOM_NODE_LIMIT:
        issues.append("large-dom")
    if dom["maxDepth"] > DOM_DEPTH_LIMIT:
        issues.append("deep-dom")
    if dom["maxChildren"] > DOM_CHILDREN_LIMIT:
        issues.append("wide-dom-node")

    # URL quality
    url_info, url_issues = _url_checks(page_url)
    issues.extend(url_issues)

    # Social tags, full inventory
    og = {}
    twitter = {}
    for name, prop, content in meta_tags:
        key = prop or name
        if key.startswith("og:") and key not in og:
            og[key] = content[:300]
        elif key.startswith("twitter:") and key not in twitter:
            twitter[key] = content[:300]
    if not og.get("og:title") and not og.get("og:image"):
        issues.append("missing-open-graph")
    elif not og.get("og:image"):
        issues.append("missing-og-image")
    og_url = og.get("og:url", "")
    if og_url and canonical:
        from sitemap import url_match_key
        if (url_match_key(og_url) or og_url) != (url_match_key(canonical) or canonical):
            issues.append("og-url-differs-from-canonical")

    # Images: hero lazy loading and dimensions
    scope = soup.find("main") or soup.body or soup
    first_img = scope.find("img") if scope is not None else None
    hero_lazy = bool(first_img is not None and (first_img.get("loading") or "").lower() == "lazy")
    if hero_lazy:
        issues.append("first-image-lazy-loaded")

    # Encoding and caching
    cache = _cache_info(headers)
    if raw_bytes >= 1024 and not cache["contentEncoding"]:
        issues.append("no-compression")

    # Microdata and RDFa
    microdata_types = sorted({str(t).rstrip("/").rsplit("/", 1)[-1]
                              for el in soup.find_all(attrs={"itemtype": True})
                              for t in str(el.get("itemtype")).split()})[:15]
    rdfa_types = sorted({str(t).rsplit(":", 1)[-1].rsplit("/", 1)[-1]
                         for el in soup.find_all(attrs={"typeof": True})
                         for t in str(el.get("typeof")).split()})[:15]

    a11y = _a11y_static(soup)
    if a11y["unlabeledInputs"]:
        issues.append(f"form-inputs-without-label ({a11y['unlabeledInputs']})")
    if a11y["unnamedButtons"]:
        issues.append(f"buttons-without-name ({a11y['unnamedButtons']})")
    if a11y["emptyLinks"]:
        issues.append(f"links-without-text ({a11y['emptyLinks']})")

    validation = _validation_errors(html)
    spelling = _spelling(visible_text, lang)
    if spelling and spelling["possibleMisspellings"]:
        issues.append(f"possible-misspellings ({len(spelling['possibleMisspellings'])})")

    checks = {
        "wordsMeasured": measurable,  # False: word count and word-based checks not measured for this language
        "textRatio": text_ratio,
        "textChars": text_chars,
        "htmlBytes": raw_bytes,
        "readability": readability(visible_text, lang),
        "titleRelevance": title_rel,
        "descriptionRelevance": desc_rel,
        "titleLength": len(title or ""),
        "descriptionLength": len(meta_description or ""),
        "doctype": has_doctype,
        "metaCharset": meta_charset or None,
        "headerCharset": header_charset or None,
        "charsetMismatch": charset_mismatch,
        "duplicateMetaTags": duplicates,
        "metaRefresh": meta_refresh or None,
        "deprecatedTags": deprecated,
        "frames": has_frames,
        "flash": has_flash,
        "placeholderText": lorem,
        "insecureLinks": insecure_links[:20],
        "mixedContent": mixed_resources[:20],
        "scripts": {"total": len(scripts), "external": len(external_scripts), "renderBlocking": blocking_scripts[:20]},
        "stylesheets": {"total": len(stylesheets), "renderBlocking": blocking_styles[:20]},
        "dom": dom,
        "url": url_info,
        "openGraph": og,
        "twitter": twitter,
        "firstImageLazy": hero_lazy,
        "cache": cache,
        "microdataTypes": microdata_types,
        "rdfaTypes": rdfa_types,
        "accessibility": a11y,
        "citability": _citability(soup, h1[0] if h1 else ""),
        "htmlValidation": validation,
        "spelling": spelling,
    }
    return {"checks": checks, "issues": issues, "simhash": simhash64(visible_text),
            "keywords": keyword_density(visible_text)}
