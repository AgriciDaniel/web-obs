"""llms.txt checks against the llmstxt.org format (v2), plus a draft built from the capture.

The format, in order: an optional byte order mark; an H1 with the site's name (the only required
part); a blockquote summary; any markdown except headings; then H2 sections holding "file lists",
each item `- [name](url)` optionally followed by `: notes`. An H2 named exactly `Optional` holds
links an agent may skip. Source: https://llmstxt.org/

Levels: "error" breaks the format, "warn" is a format deviation a parser may misread, "info" is
the spec's writing guidance or a WebObs heuristic. Only errors make the file invalid.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

from sitemap import canonicalize_crawl_url, is_same_site_host

SPEC_URL = "https://llmstxt.org/"
# WebObs heuristic, not a spec limit: the spec only asks that the file "stays small enough to fit in context".
REVIEW_BYTES = 100 * 1024
MAX_LINKS_KEPT = 500
NOTES_PER_CODE = 5
DIRECT_CHECK_LINKS = 60  # llms.txt links are the pages agents read first, so they get their own budget
DIRECT_CHECK_SECONDS = 30
DRAFT_MAX_LINKS = 60
DRAFT_SECTION_LINKS = 10

_HEADING = re.compile(r"^(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$")
# The reference parser (llms_txt) reads items as `-\s*\[title\](url)(:\s*desc)?`.
_ITEM = re.compile(r"^-\s*\[(?P<title>[^\]]+)\]\((?P<url><[^>\n]+>|(?:[^()\s<]|\([^()\s]*\))+)(?:\s+\"[^\"]*\")?\)(?P<rest>.*)$")
_BULLET = re.compile(r"^([-*+]|\d{1,3}[.)])\s+")
_FENCE = re.compile(r"^(```|~~~)")

MESSAGES = {
    "missing-h1-title": "The file must start with an H1 holding the site's name (`# Name`).",
    "multiple-h1": "More than one H1. The format has one title; later H1s read as part of the content.",
    "no-summary-blockquote": "No summary blockquote (`> One sentence about the site`) after the title.",
    "summary-not-after-title": "The summary blockquote is not directly after the title, so parsers may miss it.",
    "heading-in-details": "A heading before the first H2. Only H2 headings may split the file; use paragraphs or lists here.",
    "item-without-link": "A list item without a link in a file list section. Parsers skip it; general notes belong before the first H2.",
    "malformed-link": "This item looks meant as a link but is not written as `[name](url)`, so agents cannot follow it.",
    "link-not-at-start": "Links inside a sentence are not read as file list entries by the reference parser.",
    "bullet-not-dash": "A file list item uses `*`, `+` or a number. The reference parser reads only `-` items.",
    "notes-without-colon": "Text after a link without the `:` separator, so it is not read as the link's notes.",
    "empty-section": "An H2 section without links. In the format, H2 sections hold file lists; general text belongs before the first H2.",
    "invalid-url": "A link that is not a web address.",
    "duplicate-link": "The same address is listed more than once.",
    "relative-url": "A relative link. It works only when resolved against the file's own address; the spec's examples use full URLs.",
    "optional-heading-variant": "This looks meant as the Optional section, but only `## Optional` exactly carries that meaning.",
    "no-link-list": "No file lists. The format allows this, but links are how agents find the detail.",
    "links-without-notes": "Most links have no notes. The spec suggests a brief description for each.",
    "oversize": "Over 100 KB. The spec asks that the file stays small enough to fit in context, with detail behind the links.",
    "content-type": "Served with an unexpected content type. A markdown or plain text type is expected.",
}
LEVELS = {
    "missing-h1-title": "error", "multiple-h1": "error",
    "no-summary-blockquote": "warn", "summary-not-after-title": "warn", "heading-in-details": "warn",
    "malformed-link": "warn", "bullet-not-dash": "warn", "notes-without-colon": "warn", "invalid-url": "warn", "content-type": "warn",
    # Common, harmless to the reference parser, and not forbidden by the spec: guidance only.
    "item-without-link": "info", "link-not-at-start": "info", "empty-section": "info", "duplicate-link": "info",
    "relative-url": "info", "optional-heading-variant": "info", "no-link-list": "info",
    "links-without-notes": "info", "oversize": "info",
}


def _note(notes: list, code: str, line: int = 0, detail: str = "") -> None:
    notes.append({"line": line, "code": code, "level": LEVELS[code],
                  "message": MESSAGES[code] + (f" {detail}" if detail else "")})


def validate_llms_txt(text: str, base_url: Optional[str] = None, content_type: Optional[str] = None) -> dict:
    """Parse and check one llms.txt. `base_url` is the file's own address, for relative links and site matching."""
    raw = (text or "").lstrip("﻿")
    lines = raw.splitlines()
    notes: list[dict] = []
    title = summary = None
    h1_lines: list[int] = []
    sections: list[dict] = []
    links: list[dict] = []
    seen_urls: dict[str, int] = {}
    fence = None  # the marker that opened the current code block
    stage = "start"  # start -> title -> details -> sections
    summary_lines: list[str] = []
    first_content_after_title = None
    base_host = urlparse(base_url).hostname if base_url else None

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        opener = _FENCE.match(stripped)
        if opener and (fence is None or opener.group(1) == fence):
            fence = None if fence else opener.group(1)
            continue
        if fence or not stripped:
            if summary_lines and stage == "title":
                stage = "details"  # a blank line ends the summary blockquote
            continue
        heading = _HEADING.match(stripped)
        if stage == "start":
            if heading and len(heading.group(1)) == 1 and heading.group(2):
                title, stage = heading.group(2).strip(), "title"
                h1_lines.append(number)
                continue
            _note(notes, "missing-h1-title", number)
            stage = "details"
        if heading and len(heading.group(1)) == 1:
            h1_lines.append(number)
            continue
        if heading and len(heading.group(1)) == 2:
            stage = "sections"
            sections.append({"name": (heading.group(2) or "").strip(), "line": number, "links": 0})
            continue
        if stage == "title":
            if first_content_after_title is None:
                first_content_after_title = stripped
            if stripped.startswith(">") and (summary_lines or first_content_after_title == stripped):
                summary_lines.append(stripped.lstrip(">").strip())
                continue
            stage = "details"
        if stage == "details":
            if heading:
                _note(notes, "heading-in-details", number, f"{stripped[:80]}")
            elif stripped.startswith(">") and summary is None and not summary_lines:
                _note(notes, "summary-not-after-title", number)
                summary_lines.append(stripped.lstrip(">").strip())
            continue
        # stage == "sections": only list items carry links; prose and deeper headings are kept as content.
        section = sections[-1]
        bullet = _BULLET.match(stripped)
        if not bullet:
            continue
        body = stripped[bullet.end():]
        item = _ITEM.match("- " + body)
        if not item:
            if body.startswith("["):
                code = "malformed-link"  # meant as a link: `[Name] (url)` or a space in the URL
            elif "](" in body:
                code = "link-not-at-start"  # a sentence with links in it
            elif re.search(r"https?://", body):
                code = "malformed-link"  # a bare address, not written as a link
            else:
                code = "item-without-link"
            _note(notes, code, number, f"{stripped[:80]}")
            continue
        if bullet.group(1) != "-":
            _note(notes, "bullet-not-dash", number)
        rest = item.group("rest").strip()
        if rest and not rest.startswith(":"):
            _note(notes, "notes-without-colon", number, f"{rest[:60]}")
        href = item.group("url").strip()
        if href.startswith("<") and href.endswith(">"):
            href = href[1:-1].strip()
        parsed = urlparse(href)
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            _note(notes, "invalid-url", number, f"{href[:80]}")
            continue
        absolute = href
        if not parsed.scheme:
            _note(notes, "relative-url", number, f"{href[:80]}")
            if not base_url:
                section["links"] += 1
                continue
            absolute = urljoin(base_url, href)
        key = canonicalize_crawl_url(absolute) or absolute
        if key in seen_urls:
            _note(notes, "duplicate-link", number, f"Repeats line {seen_urls[key]}: {absolute[:80]}")
        else:
            seen_urls[key] = number
        section["links"] += 1
        if len(links) < MAX_LINKS_KEPT:
            host = urlparse(absolute).hostname or ""
            links.append({"url": absolute, "title": item.group("title").strip(), "notes": rest.lstrip(":").strip(),
                          "line": number, "section": section["name"],
                          "sameSite": bool(base_host) and is_same_site_host(host, base_host),
                          "markdown": urlparse(absolute).path.lower().endswith(".md")})

    if summary_lines:
        summary = " ".join(s for s in summary_lines if s)
    elif title is not None:
        _note(notes, "no-summary-blockquote", h1_lines[0] if h1_lines else 0)
    if len(h1_lines) > 1:
        _note(notes, "multiple-h1", h1_lines[1], f"Lines {', '.join(map(str, h1_lines[:5]))}.")
    for section in sections:
        if not section["links"]:
            _note(notes, "empty-section", section["line"], f"## {section['name'][:60]}")
        if section["name"] != "Optional" and re.fullmatch(r"optional\b.*", section["name"], re.I):
            _note(notes, "optional-heading-variant", section["line"], f"## {section['name'][:60]}")
    total_links = sum(s["links"] for s in sections)
    if not total_links:
        _note(notes, "no-link-list")
    elif sum(1 for link in links if not link["notes"]) > len(links) / 2:
        _note(notes, "links-without-notes", 0, f"{sum(1 for link in links if not link['notes'])} of {len(links)}.")
    size = len(raw.encode("utf-8", errors="replace"))
    if size > REVIEW_BYTES:
        _note(notes, "oversize", 0, f"{size // 1024} KB.")
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind and kind not in ("text/plain", "text/markdown", "text/x-markdown"):
        _note(notes, "content-type", 0, f"Served as {kind}.")
    notes.sort(key=lambda n: (n["line"] or 10**9, n["code"]))
    codes = list(dict.fromkeys(n["code"] for n in notes))
    counts = {code: sum(1 for n in notes if n["code"] == code) for code in codes}
    kept, shown = [], dict.fromkeys(codes, 0)
    for n in notes:  # one long file can repeat a pattern hundreds of times; show five of each and count the rest
        shown[n["code"]] += 1
        if shown[n["code"]] <= NOTES_PER_CODE:
            if shown[n["code"]] == NOTES_PER_CODE and counts[n["code"]] > NOTES_PER_CODE:
                n = {**n, "message": n["message"] + f" ({counts[n['code']] - NOTES_PER_CODE} more lines like this.)"}
            kept.append(n)
    notes = kept
    return {
        "valid": not any(n["level"] == "error" for n in notes),
        "issues": codes,
        "notes": notes[:200],
        "noteCounts": counts,
        "spec": SPEC_URL,
        "title": title,
        "summary": summary,
        "sections": [{"name": s["name"], "line": s["line"], "links": s["links"]} for s in sections][:100],
        "hasOptional": any(s["name"] == "Optional" for s in sections),
        "links": links,
        "stats": {"bytes": size, "approxTokens": round(len(raw) / 4), "sections": len(sections), "links": total_links,
                  "sameSiteLinks": sum(1 for link in links if link["sameSite"]),
                  "externalLinks": sum(1 for link in links if not link["sameSite"]),
                  "markdownLinks": sum(1 for link in links if link["markdown"]),
                  "linksWithNotes": sum(1 for link in links if link["notes"])},
        "contentType": kind or None,
    }


def validate_llms_full_txt(text: str, content_type: Optional[str] = None) -> dict:
    """llms-full.txt is a common convention (the whole content in one file), not part of the spec."""
    raw = (text or "").lstrip("﻿")
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    issues = [] if re.match(r"^#\s+\S", first) else ["missing-h1-title"]
    return {"valid": True, "convention": True, "issues": issues,
            "stats": {"bytes": len(raw.encode("utf-8", errors="replace")), "approxTokens": round(len(raw) / 4)},
            "contentType": (content_type or "").split(";")[0].strip().lower() or None}


# Links: what the capture already knows about each llms.txt link

def link_report(validation: dict, nodes: Iterable[dict], url_aliases: dict, robots_allowed, checked: Optional[dict] = None,
                unchecked_detail: Optional[str] = None) -> list[dict]:
    """One row per llms.txt link: ok, redirect, broken, unavailable, noindex, non-canonical, blocked, unchecked.

    `nodes` are the captured pages, `url_aliases` maps redirected URLs to their final page, `robots_allowed(url)`
    answers from robots.txt files already read, and `checked` holds direct checks of links the crawl did not reach.
    """
    by_url = {}
    for node in nodes:
        key = canonicalize_crawl_url(node["url"]) or node["url"]
        by_url[key] = node
    rows = []
    for link in validation.get("links") or []:
        url = link["url"]
        row = {"url": url, "line": link["line"], "section": link["section"], "title": link["title"], "sameSite": link["sameSite"]}
        if not link["sameSite"]:
            rows.append({**row, "state": "external", "detail": "Another site, not checked."})
            continue
        key = canonicalize_crawl_url(url) or url
        node = by_url.get(key) or by_url.get(canonicalize_crawl_url(url_aliases.get(key, "")) or "")
        if not robots_allowed(url):
            rows.append({**row, "state": "blocked", "detail": "robots.txt does not allow crawlers to fetch it."})
        elif node:
            status = node.get("statusCode") or 0
            canonical = canonicalize_crawl_url(node.get("canonical") or "") if node.get("canonical") else None
            if status in (404, 410):
                state, detail = "broken", f"HTTP {status}."
            elif status >= 400 or not status or node.get("error"):
                state, detail = "unavailable", node.get("error") or f"HTTP {status}."
            elif key in url_aliases or key != (canonicalize_crawl_url(node["url"]) or node["url"]):
                state, detail = "redirect", f"Redirects to {node['url']}."
            elif "noindex" in (node.get("metaRobots") or "").lower():
                state, detail = "noindex", "The page asks search engines not to index it."
            elif canonical and canonical != (canonicalize_crawl_url(node["url"]) or node["url"]):
                state, detail = "non-canonical", f"Its canonical is {node['canonical']}."
            else:
                state, detail = "ok", f"Captured, HTTP {status}."
            rows.append({**row, "state": state, "detail": detail, "statusCode": status or None})
        elif checked and url in checked:
            result = checked[url]
            status = result.get("statusCode")
            mapped = {"ok": "ok", "broken": "broken", "server-error": "unavailable"}.get(result.get("status"))
            if mapped is None and status and 300 <= status < 400:
                mapped = "redirect"
            rows.append({**row, "state": mapped or "unchecked", "statusCode": status,
                         "detail": (f"Checked directly, HTTP {status}." if status else result.get("reason") or "Not confirmed.")})
        else:
            detail = unchecked_detail or ("Not captured, and the direct checks did not reach it "
                      f"(up to {DIRECT_CHECK_LINKS} links in {DIRECT_CHECK_SECONDS} s)." if checked is not None else "Not captured and not checked.")
            rows.append({**row, "state": "unchecked", "detail": detail})
    return rows


def links_to_check(rows: list[dict], limit: int = DIRECT_CHECK_LINKS) -> list[str]:
    return [r["url"] for r in rows if r["state"] == "unchecked" and r["sameSite"]][:limit]


# Findings

def _finding(fid: str, tone: str, title: str, explanation: str, targets: list[dict]) -> dict:
    return {"id": fid, "category": "structure", "tone": tone, "title": title, "explanation": explanation,
            "targets": targets[:200], "targetCount": len(targets)}


def llms_findings(ai_intel: dict, origin: str) -> list[dict]:
    """Findings for llms.txt. They only exist when the llms.txt check got an answer from the site."""
    file_url = origin.rstrip("/") + "/llms.txt"
    probe = (ai_intel.get("llmsProbe") or {}).get("llmsTxt") or {}
    state = probe.get("state")
    validation = (ai_intel.get("validation") or {}).get("llmsTxt") or {}
    out: list[dict] = []
    draft_note = " A draft built from this capture is in _llms-txt-draft.md." if (ai_intel.get("llmsDraft") or {}).get("path") else ""
    # A missing file is information, not a task: Google Search ignores llms.txt, Lighthouse marks a 404 as not
    # applicable, and no major AI assistant documents reading it. Tools that are pointed at a site may still use it.
    optional = (" It is optional: Google Search ignores it and it does not affect rankings, but coding tools and "
                "assistants that are given your site can use it.")
    if state == "absent":
        out.append(_finding("llmstxt-missing", "coverage", "No llms.txt",
                            "llms.txt is a plain markdown index that points AI agents at your key pages." + optional + draft_note,
                            [{"url": file_url, "detail": f"HTTP {probe.get('statusCode')}."}]))
    elif state == "html":
        out.append(_finding("llmstxt-serves-html", "coverage", "llms.txt address serves a web page",
                            "The address answers with an HTML page instead of a markdown file, so agents find no llms.txt." + optional + draft_note,
                            [{"url": file_url, "detail": "HTML returned with HTTP 200."}]))
    elif state == "unavailable" and (probe.get("statusCode") or 0) >= 500:
        out.append(_finding("llmstxt-server-error", "attention", "llms.txt returns a server error",
                            "The server fails when asked for /llms.txt. Chrome Lighthouse fails its llms.txt check for this, "
                            "and agents get an error instead of a file or a clean 404.",
                            [{"url": file_url, "detail": f"HTTP {probe.get('statusCode')}."}]))
    if state != "found" or not validation:
        return out
    format_notes = [n for n in validation.get("notes") or [] if n["level"] in ("error", "warn")]
    if format_notes:
        tone = "attention" if not validation.get("valid") else "review"
        out.append(_finding("llmstxt-format", tone, "llms.txt format problems" if tone == "attention" else "llms.txt format notes",
                            "Lines that do not follow the llmstxt.org format, so agents and parsers may misread them.",
                            [{"url": file_url, "detail": (f"Line {n['line']}: " if n["line"] else "") + n["message"]} for n in format_notes]))
    rows = ai_intel.get("llmsLinks") or []
    dead = [r for r in rows if r["state"] in ("broken", "unavailable", "blocked")]
    if dead:
        out.append(_finding("llmstxt-dead-links", "attention", "llms.txt links agents cannot use",
                            "These links in llms.txt point at pages that are missing, failing or blocked by robots.txt.",
                            [{"url": r["url"], "sourceUrl": file_url, "detail": f"Line {r['line']}: {r['state']}. {r['detail']}"} for r in dead]))
    loose = [r for r in rows if r["state"] in ("redirect", "noindex", "non-canonical")]
    if loose:
        out.append(_finding("llmstxt-link-hygiene", "review", "llms.txt links that could be more direct",
                            "These links redirect, point at a page that asks not to be indexed, or at a non-canonical address. "
                            "Link the final, canonical page.",
                            [{"url": r["url"], "sourceUrl": file_url, "detail": f"Line {r['line']}: {r['state']}. {r['detail']}"} for r in loose]))
    user_bots = ai_intel.get("userTriggeredBots") or []
    policy = ai_intel.get("aiBotsPolicy") or {}
    blocked = [b for b in user_bots if str(policy.get(b, "")).startswith("blocked")]
    if blocked:
        out.append(_finding("llmstxt-agents-blocked", "review", "llms.txt is offered, but robots.txt blocks the agents that read it",
                            "Agents that fetch pages when a person asks them to are blocked in robots.txt, so they cannot follow the llms.txt links.",
                            [{"url": origin.rstrip("/") + "/robots.txt", "detail": ", ".join(blocked)}]))
    return out


MARKDOWN_CHECK_PAGES = 10
MARKDOWN_CHECK_SECONDS = 15


def check_markdown_copy(url: str, timeout: float) -> dict:
    """GET a declared markdown copy and say whether it is one: HTTP 200 and not an HTML page."""
    from url_safety import DEFAULT_REQUEST_HEADERS, safe_requests_session
    try:
        with safe_requests_session(url) as session:
            response = session.get(url, headers={**DEFAULT_REQUEST_HEADERS, "Accept": "text/markdown, text/plain;q=0.9, */*;q=0.1"},
                                   timeout=timeout, stream=True)
            try:
                status = response.status_code
                kind = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                head = response.raw.read(2048, decode_content=True).decode("utf-8", errors="replace").lstrip().lower()
            finally:
                response.close()
    except Exception as exc:  # a refused, failed or timed-out request is not a verdict on the copy
        return {"state": "unchecked", "statusCode": None, "detail": f"Not checked ({type(exc).__name__})."}
    if status != 200:
        return {"state": "broken" if status in (404, 410) else "unavailable", "statusCode": status, "detail": f"HTTP {status}."}
    if kind == "text/html" or head.startswith(("<!doctype html", "<html")):
        return {"state": "html", "statusCode": status, "detail": "Returns an HTML page, not markdown."}
    return {"state": "ok", "statusCode": status, "detail": f"Markdown served ({kind or 'no content type'})."}


def markdown_findings(rows: list[dict]) -> list[dict]:
    """Pages that declare a markdown version (llms.txt v2) that does not load as markdown."""
    bad = [r for r in rows if r["state"] in ("broken", "unavailable", "html")]
    if not bad:
        return []
    return [{"id": "markdown-alternate-broken", "category": "structure", "tone": "review",
             "title": "Declared markdown versions that do not load",
             "explanation": "These pages point agents at a markdown copy (rel=\"alternate\" type=\"text/markdown\"), but the copy is missing, "
                            "fails, or is an HTML page. Fix the copy or remove the pointer.",
             "targets": [{"url": r["page"], "detail": f"{r['url']}: {r['detail']}"} for r in bad][:200], "targetCount": len(bad)}]


# Draft: an llms.txt built only from what this capture observed

def _clean(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    text = text.replace("[", "(").replace("]", ")")
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "..."


# Policy and legal pages are worth listing, but they are secondary: they go under Optional.
_SECONDARY_SEGMENT = re.compile(r"^(privacy|cookies?|terms|tos|legal|imprint|impressum|disclaimer|accessibility|gdpr|ccpa|sitemap)([-_.].*)?$", re.I)
_TITLE_SEPARATORS = r"[|\-\u2013\u2014\u00b7:]"


def strip_brand(title: str, brand: str) -> str:
    """'Pricing | Brand' and 'Brand | Pricing' become 'Pricing'; inside the site's own llms.txt the brand is noise."""
    if not brand:
        return title
    name = re.escape(brand.strip())
    stripped = re.sub(rf"\s*{_TITLE_SEPARATORS}\s*{name}\s*$", "", title, flags=re.I)
    stripped = re.sub(rf"^\s*{name}\s*{_TITLE_SEPARATORS}\s*", "", stripped, flags=re.I)
    return stripped.strip() or title


def is_secondary_page(url: str) -> bool:
    """Policy pages live at the top of a site (/privacy-policy, /legal/...), so only the first segment is read."""
    first = ((urlparse(url).path or "/").strip("/").split("/") or [""])[0]
    return bool(_SECONDARY_SEGMENT.match(first))


def _section_name(section: str) -> str:
    return section.replace("-", " ").replace("_", " ").strip().capitalize() or "Pages"


def draft_llms_txt(brand: str, home_url: str, nodes: list[dict], markdown_alternates: Optional[dict] = None) -> dict:
    """A starting llms.txt from captured pages that are live, indexable and canonical, strongest first.

    Notes come from each page's own meta description. Where a page declares a markdown version, the
    draft links that, as the spec suggests. Nothing is invented: a page without a description has no notes.
    """
    markdown_alternates = markdown_alternates or {}
    home_key = canonicalize_crawl_url(home_url) or home_url

    def eligible(n):
        if n.get("kind") == "external-domain" or n.get("statusCode") != 200 or n.get("redirectChain"):
            return False
        if "noindex" in (n.get("metaRobots") or "").lower():
            return False
        canonical = n.get("canonical")
        own = canonicalize_crawl_url(n["url"]) or n["url"]
        return not canonical or (canonicalize_crawl_url(canonical) or canonical) == own

    pages = sorted((n for n in nodes if eligible(n)), key=lambda n: (-(n.get("authorityScore") or 0), n["url"]))
    home = next((n for n in pages if (canonicalize_crawl_url(n["url"]) or n["url"]) == home_key), None)
    summary = _clean((home or {}).get("metaDescription") or "", 300)

    def item(n):
        url = (markdown_alternates.get(n["url"]) or [n["url"]])[0]
        title = _clean(strip_brand(n.get("title") or n.get("path") or url, brand), 90) or url
        notes = _clean(n.get("metaDescription") or "", 160)
        if n is home and notes and notes.rstrip(".") == summary[:160].rstrip("."):
            notes = ""  # the summary already says it
        return f"- [{title}]({url})" + (f": {notes}" if notes else "")

    rest = [n for n in pages if n is not home and not is_secondary_page(n["url"])]
    secondary = [n for n in pages if n is not home and is_secondary_page(n["url"])]
    groups: dict[str, list[dict]] = {}
    for n in rest:
        groups.setdefault(n.get("section") or "", []).append(n)
    used = 0
    main_lines: list[str] = [item(home)] if home else []
    used += len(main_lines)
    blocks: list[str] = []
    optional: list[str] = []
    top_level = groups.pop("", []) + groups.pop("root", [])
    for name in [k for k, members in groups.items() if len(members) == 1 and (members[0].get("urlDepth") or 0) <= 1]:
        top_level += groups.pop(name)  # a lone /about is a main page, not a section of its own
    top_level.sort(key=lambda n: (-(n.get("authorityScore") or 0), n["url"]))
    for n in top_level:
        if used < DRAFT_MAX_LINKS and len(main_lines) < DRAFT_SECTION_LINKS:
            main_lines.append(item(n))
            used += 1
        else:
            optional.append(item(n))
    ranked = sorted(groups.items(), key=lambda kv: (-sum(n.get("authorityScore") or 0 for n in kv[1]), kv[0]))
    for name, members in ranked:
        kept = []
        for n in members:
            if used < DRAFT_MAX_LINKS and len(kept) < DRAFT_SECTION_LINKS:
                kept.append(item(n))
                used += 1
            else:
                optional.append(item(n))
        if kept:
            blocks.append(f"## {_section_name(name)}\n\n" + "\n".join(kept))
    optional = (optional + [item(n) for n in secondary])[: max(0, DRAFT_MAX_LINKS - used) + 20]
    parts = [f"# {_clean(brand, 120) or urlparse(home_url).hostname}"]
    if summary:
        parts.append(f"> {summary}")
    if main_lines:
        parts.append("## Main pages\n\n" + "\n".join(main_lines))
    parts += blocks
    if optional:
        parts.append("## Optional\n\n" + "\n".join(optional))
    text = "\n\n".join(parts) + "\n"
    return {"text": text, "pages": text.count("\n- ["), "hasSummary": bool(summary),
            "markdownLinks": sum(1 for n in pages if markdown_alternates.get(n["url"]))}


def write_draft_note(site_root: str, domain_folder: str, captured_iso: str, draft: dict, validation: Optional[dict],
                     missing_strong_pages: list[dict]) -> str:
    import os
    lines = ["---", "tags:", "  - web-obs", "  - web-obs/llms-txt", f"captured_at: \"{captured_iso}\"", "---", "",
             "# llms.txt draft", "",
             "Built only from this capture: live, indexable, canonical pages, strongest first, with each page's own meta description as its notes. "
             "Review it, then publish it as plain text at `/llms.txt`. Format: [llmstxt.org](https://llmstxt.org/).", ""]
    if not draft["hasSummary"]:
        lines += ["> [!warning] No summary", "> The home page has no meta description, so the draft has no summary line. Add `> One sentence about the site` under the title.", ""]
    if validation and missing_strong_pages:
        lines += ["## Strong pages your llms.txt does not list", ""]
        lines += [f"- [{_clean(n.get('title') or n['url'], 90)}]({n['url']})" for n in missing_strong_pages]
        lines += [""]
    lines += ["## Draft", "", "```markdown", draft["text"].rstrip("\n"), "```", ""]
    path = os.path.join(site_root, "_llms-txt-draft.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return f"sites/{domain_folder}/_llms-txt-draft.md"
