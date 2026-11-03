#!/usr/bin/env python3
"""
Step 1 of web-obs: Sitemap-first URL discovery and recursive expansion.

Discovers sitemaps through robots.txt and common paths (/sitemap.xml,
/sitemap_index.xml, /sitemap-index.xml, /wp-sitemap.xml) and recursively
expands <sitemapindex>, <urlset>, gzipped (.xml.gz) sitemaps, RSS/Atom feeds,
and plain-text sitemaps into normalized same-site URL records.
"""

from __future__ import annotations

import gzip
import io
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from lxml import etree

from url_safety import DEFAULT_REQUEST_HEADERS, URLSafetyError, safe_requests_session, validate_url
from site_intel import build_robots_policy, robots_url_decision

COMMON_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/page-sitemap.xml",
    "/post-sitemap.xml",
)

MAX_DECLARED_SITEMAPS = 24
MAX_CHILD_SITEMAPS = 40
MAX_ROBOTS_BYTES = 1024 * 1024
MAX_SITEMAP_BYTES = 32 * 1024 * 1024
MAX_URLS_FROM_SITEMAPS = 5000
USER_AGENT = DEFAULT_REQUEST_HEADERS["User-Agent"]
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)\s*$", re.IGNORECASE)


@dataclass
class SitemapUrlEntry:
    url: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[str] = None
    source_sitemap: Optional[str] = None


@dataclass
class SitemapDiscoveryResult:
    origin: str
    robots_url: str
    robots_text: str = ""
    robots_status_code: Optional[int] = None
    robots_error: Optional[str] = None
    robots_too_large: bool = False
    robots_policy: dict = field(default_factory=dict)
    sitemaps_found: list[dict] = field(default_factory=list)
    entries: dict[str, SitemapUrlEntry] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def normalize_domain_host(hostname: str) -> str:
    h = (hostname or "").lower().strip().rstrip(".")
    if h.startswith("www."):
        return h[4:]
    return h


def is_same_site_host(candidate_host: str, target_host: str) -> bool:
    return normalize_domain_host(candidate_host) == normalize_domain_host(target_host)


def canonicalize_crawl_url(url: str) -> Optional[str]:
    """Normalize a URL to its published form (no fragment or tracking params, trailing slash kept)."""
    if not url or any(c.isspace() for c in url):
        return None
    try:
        parsed = urlparse(url.strip())
        _ = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None

    host = parsed.hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default_port = 443 if scheme == "https" else 80
    netloc = f"{host}:{port}" if port and port != default_port else host

    # The trailing slash is part of the published address. A site that serves
    # /about/ answers /about with a redirect, so it must not be stripped here.
    path = re.sub(r"/{2,}", "/", parsed.path or "/")

    # Strip noisy marketing query params while preserving meaningful query keys if non-tracking
    clean_query = ""
    if parsed.query:
        kept: list[str] = []
        for pair in parsed.query.split("&"):
            if not pair:
                continue
            key = unquote(pair.split("=", 1)[0]).lower()
            if key.startswith("utm_") or key in {"fbclid", "gclid", "mc_cid", "mc_eid", "_ga", "ref"}:
                continue
            kept.append(pair)
        clean_query = "&".join(kept)

    return urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))


def url_match_key(url: str) -> Optional[str]:
    """Slash-insensitive key for deciding that two URL forms name the same page.

    Use it to match or deduplicate. Never fetch or store it: the published form
    from canonicalize_crawl_url is the address a site actually serves.
    """
    canonical = canonicalize_crawl_url(url)
    if canonical is None:
        return None
    parsed = urlparse(canonical)
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ""))


def _origin_from_target(target_url: str) -> str:
    url = target_url.strip()
    if "://" not in url:
        url = f"https://{url}"
    if not validate_url(url):
        raise ValueError(f"Target must be a valid HTTP or HTTPS URL: {target_url}")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = f"{host}:{port}" if port and port != default_port else host
    return urlunparse((parsed.scheme.lower(), netloc, "", "", "", ""))


def _bounded_fetch_bytes(
    url: str, max_bytes: int = MAX_SITEMAP_BYTES,
    allowed_callback: Optional[Callable[[str], bool]] = None,
) -> dict:
    out = {
        "status_code": None,
        "content": b"",
        "content_type": "",
        "final_url": url,
        "too_large": False,
        "error": None,
    }
    deadline = time.monotonic() + 20
    current = url
    try:
        for hop in range(6):
            if allowed_callback is not None and not allowed_callback(current):
                out["error"] = "Fetch refused by robots policy."
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                out["error"] = "Fetch time budget reached."
                break
            with safe_requests_session(current) as session:
                resp = session.get(
                    current,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/xml,text/xml,text/plain,*/*",
                    },
                    timeout=max(0.001, min(10, remaining / 2)),
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    out["status_code"] = resp.status_code
                    out["content_type"] = resp.headers.get("Content-Type", "")
                    out["final_url"] = current
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location")
                        if not location or hop == 5:
                            out["error"] = "Redirect is missing a target or exceeds five hops."
                            break
                        current = urljoin(current, location)
                        continue
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        if time.monotonic() >= deadline:
                            out["error"] = "Fetch time budget reached."
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            out["too_large"] = True
                            break
                        chunks.append(chunk)
                    out["content"] = b"".join(chunks)
                    break
                finally:
                    resp.close()
    except URLSafetyError as exc:
        out["error"] = f"URL safety validation failed: {exc}"
    except requests.exceptions.RequestException as exc:
        out["error"] = f"Request failed: {exc}"
    except (ValueError, OSError) as exc:
        out["error"] = f"Fetch failed: {type(exc).__name__}"
    return out


def _maybe_decompress_gzip(raw: bytes, url: str, content_type: str) -> bytes:
    is_gz = (
        raw[:2] == b"\x1f\x8b"
        or urlparse(url).path.lower().endswith(".gz")
        or "gzip" in (content_type or "").lower()
    )
    if not is_gz:
        return raw
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            return gz.read(MAX_SITEMAP_BYTES + 1)
    except OSError:
        return raw


def _local_tag(elem) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def _parse_sitemap_payload(
    raw: bytes,
    content_type: str,
    final_url: str,
    on_warning: Optional[Callable[[str], None]] = None,
) -> tuple[Optional[str], list[str], list[SitemapUrlEntry], Optional[str]]:
    """
    Returns (kind, child_sitemaps, url_entries, error).
    """
    payload = _maybe_decompress_gzip(raw, final_url, content_type)
    if len(payload) > MAX_SITEMAP_BYTES:
        return None, [], [], "Uncompressed sitemap exceeds limit"
    if not payload.strip():
        return None, [], [], "Empty response"

    stripped = payload.lstrip()
    if stripped[:256].upper().find(b"<!DOCTYPE") != -1:
        return None, [], [], "HTML or DOCTYPE document instead of sitemap"

    if stripped.startswith(b"<"):
        try:
            parser = etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                recover=False,
                huge_tree=False,
            )
            root = etree.fromstring(payload, parser=parser)
        except (etree.XMLSyntaxError, ValueError):
            return None, [], [], "Invalid XML"

        kind = _local_tag(root)
        if kind == "sitemapindex":
            children: list[str] = []
            for sm in root:
                if _local_tag(sm) != "sitemap":
                    continue
                for child in sm:
                    if _local_tag(child) == "loc" and child.text:
                        loc = child.text.strip()
                        if loc:
                            children.append(loc)
            return "sitemapindex", children, [], None

        if kind == "urlset":
            entries: list[SitemapUrlEntry] = []
            for u_el in root:
                if _local_tag(u_el) != "url":
                    continue
                loc = None
                lastmod = None
                changefreq = None
                priority = None
                for field_el in u_el:
                    ftag = _local_tag(field_el)
                    val = (field_el.text or "").strip()
                    if not val:
                        continue
                    if ftag == "loc":
                        loc = val
                    elif ftag == "lastmod":
                        lastmod = val
                    elif ftag == "changefreq":
                        changefreq = val
                    elif ftag == "priority":
                        priority = val
                if loc:
                    entries.append(
                        SitemapUrlEntry(
                            url=loc,
                            lastmod=lastmod,
                            changefreq=changefreq,
                            priority=priority,
                            source_sitemap=final_url,
                        )
                    )
            return "urlset", [], entries, None

        if kind in ("rss", "feed"):
            entries = []
            for elem in root.iter():
                lt = _local_tag(elem)
                if lt == "link":
                    href = elem.get("href") or (elem.text or "").strip()
                    if href and href.startswith(("http://", "https://")):
                        entries.append(SitemapUrlEntry(url=href, source_sitemap=final_url))
            return kind, [], entries, None

        return None, [], [], f"Unsupported XML root <{kind}>"

    if "text/plain" in (content_type or "").lower() or urlparse(final_url).path.lower().endswith(".txt"):
        lines = [
            ln.strip()
            for ln in payload.decode("utf-8", errors="replace").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if lines and all(ln.startswith(("http://", "https://")) for ln in lines[:50]):
            if len(lines) > MAX_URLS_FROM_SITEMAPS and on_warning:
                on_warning(f"Sitemap URL inventory limit reached ({MAX_URLS_FROM_SITEMAPS}); additional URLs were not retained.")
            entries = [
                SitemapUrlEntry(url=ln, source_sitemap=final_url)
                for ln in lines[:MAX_URLS_FROM_SITEMAPS]
            ]
            return "text", [], entries, None

    return None, [], [], "Not a recognized sitemap format"


def discover_and_expand_sitemaps(
    target_url: str,
    on_progress: Optional[Callable[[str, int, int], None]] = None,
) -> SitemapDiscoveryResult:
    origin = _origin_from_target(target_url)
    target_host = urlparse(origin).hostname or ""
    robots_url = f"{origin}/robots.txt"
    result = SitemapDiscoveryResult(origin=origin, robots_url=robots_url)
    warned: set[str] = set()

    def warn(message: str) -> None:
        if message not in warned:
            warned.add(message)
            result.warnings.append(message)

    declared: list[str] = []
    robots_resp = _bounded_fetch_bytes(robots_url, MAX_ROBOTS_BYTES)
    result.robots_status_code = robots_resp["status_code"]
    result.robots_error = robots_resp["error"]
    result.robots_too_large = robots_resp["too_large"]
    if isinstance(robots_resp["status_code"], int) and 200 <= robots_resp["status_code"] < 300 and not robots_resp["error"] and not robots_resp["too_large"]:
        text = robots_resp["content"].decode("utf-8", errors="replace")
        result.robots_text = text
        for line in text.splitlines():
            m = _SITEMAP_LINE.match(line)
            if m and m.group(1) not in declared:
                if len(declared) >= MAX_DECLARED_SITEMAPS:
                    warn(f"Declared sitemap limit reached ({MAX_DECLARED_SITEMAPS}); additional declarations were not followed.")
                    continue
                declared.append(m.group(1))
    result.robots_policy = build_robots_policy(
        result.robots_text, result.robots_status_code, result.robots_error, result.robots_too_large,
    )
    policies = {origin: result.robots_policy}
    if not result.robots_policy["canCrawl"]:
        warn(result.robots_policy["reason"])

    def sitemap_allowed(target: str) -> bool:
        try:
            target_origin = _origin_from_target(target)
            if target_origin not in policies:
                fetched = _bounded_fetch_bytes(f"{target_origin}/robots.txt", MAX_ROBOTS_BYTES)
                policies[target_origin] = build_robots_policy(
                    fetched["content"].decode("utf-8", errors="replace"),
                    fetched["status_code"], fetched["error"], fetched["too_large"],
                )
                if fetched["too_large"]:
                    warn(f"Robots response exceeded byte limit: {target_origin}/robots.txt")
            decision = robots_url_decision(policies[target_origin], target)
            if not decision["allowed"]:
                warn(f"Sitemap skipped by robots policy: {target} ({decision['status']})")
            return decision["allowed"]
        except ValueError:
            warn(f"Invalid sitemap target skipped: {target}")
            return False

    queue: list[tuple[str, str]] = [(u, "robots.txt") for u in declared]
    for path in COMMON_SITEMAP_PATHS:
        cand = f"{origin}{path}"
        if all(cand != existing for existing, _ in queue):
            queue.append((cand, "common_path"))

    visited_sitemaps: set[str] = set()
    scheduled_sitemaps = {url for url, _ in queue}
    child_fetches = 0

    idx = 0
    while idx < len(queue):
        sm_url, source = queue[idx]
        idx += 1
        if sm_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sm_url)

        if on_progress:
            on_progress(sm_url, len(result.sitemaps_found), len(result.entries))

        fetched = _bounded_fetch_bytes(sm_url, MAX_SITEMAP_BYTES, allowed_callback=sitemap_allowed)
        status = fetched["status_code"]
        if fetched["too_large"]:
            warn(f"Sitemap response exceeded byte limit: {sm_url}")
        if fetched["error"] or fetched["too_large"] or status is None or not (200 <= status < 300):
            continue

        kind, children, entries, err = _parse_sitemap_payload(
            fetched["content"], fetched["content_type"], fetched["final_url"], on_warning=warn,
        )
        if not kind or err:
            if err == "Uncompressed sitemap exceeds limit":
                warn(f"Uncompressed sitemap exceeded byte limit: {sm_url}")
            continue

        final_sitemap_url = fetched["final_url"]
        if final_sitemap_url in {row["url"] for row in result.sitemaps_found}:
            # Several paths can redirect to one sitemap (Rank Math sends /sitemap.xml
            # to /sitemap_index.xml). Count the file once and do not re-read its URLs.
            visited_sitemaps.add(final_sitemap_url)
            continue
        visited_sitemaps.add(final_sitemap_url)
        result.sitemaps_found.append(
            {
                "url": final_sitemap_url,
                "source": source,
                "kind": kind,
                "url_count": len(entries),
                "child_count": len(children),
            }
        )

        for child_sm in children:
            if child_sm in visited_sitemaps or child_sm in scheduled_sitemaps:
                continue
            if child_fetches >= MAX_CHILD_SITEMAPS:
                warn(f"Child sitemap limit reached ({MAX_CHILD_SITEMAPS}); additional child sitemaps were not followed.")
                continue
            queue.append((child_sm, "sitemapindex"))
            scheduled_sitemaps.add(child_sm)
            child_fetches += 1

        for item in entries:
            norm = canonicalize_crawl_url(item.url)
            if not norm:
                continue
            item_host = urlparse(norm).hostname or ""
            if not is_same_site_host(item_host, target_host):
                continue
            item.url = norm
            if norm not in result.entries:
                if len(result.entries) >= MAX_URLS_FROM_SITEMAPS:
                    warn(f"Sitemap URL inventory limit reached ({MAX_URLS_FROM_SITEMAPS}); additional URLs were not retained.")
                    continue
                result.entries[norm] = item

    return result
