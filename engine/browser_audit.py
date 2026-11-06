"""Optional browser audit of a few sampled pages: lab timings, JavaScript content gap,
automated accessibility rules (axe-core), screenshots and third parties on first load.

Every observation comes from one local headless load through the same guarded browser
routes the capture uses. Nothing here is field data, a consent assessment or a full
accessibility review, and each result says so.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from browser_runtime import resolve_chromium_executable
from page_fetch import MAX_HTML_BYTES, _BROWSER_TRANSPORT_ARGS, _TRANSPORT_GUARD
from sitemap import is_same_site_host
from url_safety import DEFAULT_REQUEST_HEADERS, make_safe_playwright_route_handler

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Optional: the audit reports itself as skipped.
    sync_playwright = None

try:
    import lxml  # noqa: F401
    _PARSER = "lxml"
except ImportError:
    _PARSER = "html.parser"

AXE_PATH = Path(__file__).resolve().parent / "vendor" / "axe.min.js"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
MAX_SAMPLE = 5
LAB_NOTE = "One lab load on this machine through the capture proxy. Not field data."
THIRD_PARTY_NOTE = ("Observed on first load with no interaction. Not a consent or legal assessment. "
                    "The capture proxy does not apply HTTP Set-Cookie headers, so listed cookies were set by page scripts.")
JS_GAP_PCT = 30
SLOW_LCP_MS = 4000

_LAB_OBSERVER = r"""
(() => {
    const state = { lcp: 0, cls: 0 };
    Object.defineProperty(globalThis, '__webObsLab', { value: state, enumerable: false, configurable: false, writable: false });
    try {
        new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) state.lcp = Math.max(state.lcp, entry.renderTime || entry.loadTime || entry.startTime || 0);
        }).observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (_) {}
    try {
        new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) if (!entry.hadRecentInput) state.cls += entry.value;
        }).observe({ type: 'layout-shift', buffered: true });
    } catch (_) {}
})();
"""

_LAB_READ = r"""() => {
    const lab = globalThis.__webObsLab || { lcp: 0, cls: 0 };
    const nav = performance.getEntriesByType('navigation')[0];
    const resources = performance.getEntriesByType('resource');
    let bytes = nav ? (nav.encodedBodySize || nav.transferSize || 0) : 0;
    for (const entry of resources) bytes += entry.encodedBodySize || entry.transferSize || 0;
    return {
        lcpMs: Math.round(lab.lcp || 0),
        cls: Math.round((lab.cls || 0) * 1000) / 1000,
        domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd) : 0,
        loadMs: nav ? Math.round(nav.loadEventEnd) : 0,
        transferBytes: Math.round(bytes),
    };
}"""

_AXE_RUN = r"""async (tags) => {
    if (!globalThis.axe || typeof globalThis.axe.run !== 'function') return { error: 'axe-core did not load in the page.' };
    const result = await globalThis.axe.run(document, { runOnly: { type: 'tag', values: tags }, resultTypes: ['violations'] });
    return {
        version: globalThis.axe.version,
        passes: result.passes.length,
        violations: result.violations.map((v) => ({ id: v.id, impact: v.impact || 'unknown', help: v.help, nodes: v.nodes.length })),
    };
}"""

_HOST_CATEGORIES = (
    ("analytics", ("google-analytics.", "googletagmanager.", "analytics.", "clarity.ms", "plausible.", "posthog.",
                   "segment.", "hotjar.", "mixpanel.", "amplitude.", "heap.", "matomo.", "stats.", "cloudflareinsights.")),
    ("ads", ("doubleclick.", "googlesyndication.", "googleadservices.", "adservice.", "criteo.", "taboola.",
             "outbrain.", "bat.bing.", "ads.", "adnxs.", "amazon-adsystem.", "connect.facebook.net")),
    ("social", ("facebook.", "fbcdn.", "twitter.", "twimg.", "x.com", "linkedin.", "licdn.", "tiktok.",
                "pinterest.", "instagram.", "youtube.", "ytimg.", "vimeo.")),
    ("cdn", ("cdn", "jsdelivr.", "unpkg.", "cloudflare.", "fonts.googleapis.", "fonts.gstatic.", "gstatic.",
             "akamai", "fastly", "cloudfront.", "bootstrapcdn.")),
)


def categorize_host(host: str) -> str:
    low = (host or "").lower()
    for category, needles in _HOST_CATEGORIES:
        if any(needle in low for needle in needles):
            return category
    return "other"


def _skipped(detail: str) -> dict:
    return {"state": "skipped", "detail": detail, "pages": [], "findings": []}


def page_signals(html: str) -> dict:
    """Words, links, JSON-LD types and H1 text, counted the same way for raw and rendered HTML."""
    soup = BeautifulSoup(html or "", _PARSER)
    schema_types: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        for match in re.finditer(r'"@type"\s*:\s*(\[[^\]]*\]|"[^"]+")', script.string or script.get_text() or ""):
            for name in re.findall(r'"([^"]+)"', match.group(1)):
                if name not in schema_types:
                    schema_types.append(name)
    h1 = [re.sub(r"\s+", " ", tag.get_text(" ", strip=True)) for tag in soup.find_all("h1")]
    h1 = [text for text in h1 if text][:4]
    links = 0
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip().lower()
        if href and not href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            links += 1
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "template"]):
        tag.decompose()
    words = len(re.findall(r"\b\w+\b", soup.get_text(" ", strip=True)))
    return {"words": words, "links": links, "schemaTypes": schema_types[:12], "h1": h1}


def js_gap(raw_html: Optional[str], rendered_html: str) -> Optional[dict]:
    if not raw_html:
        return None
    raw, rendered = page_signals(raw_html), page_signals(rendered_html)
    added = rendered["words"] - raw["words"]
    pct = int(round(added * 100 / rendered["words"])) if rendered["words"] > 0 and added > 0 else 0
    return {"rawWords": raw["words"], "renderedWords": rendered["words"],
            "rawLinks": raw["links"], "renderedLinks": rendered["links"],
            "rawSchemaTypes": raw["schemaTypes"], "renderedSchemaTypes": rendered["schemaTypes"],
            "rawH1": raw["h1"], "renderedH1": rendered["h1"], "wordsAddedByJsPct": pct}


def js_gap_reasons(gap: Optional[dict]) -> list[str]:
    if not gap:
        return []
    reasons = []
    if gap["wordsAddedByJsPct"] >= JS_GAP_PCT:
        reasons.append(f"{gap['wordsAddedByJsPct']}% of visible words appear only after JavaScript runs ({gap['rawWords']} raw, {gap['renderedWords']} rendered)")
    if gap["renderedLinks"] >= gap["rawLinks"] * 1.3 + 3:
        reasons.append(f"links grow from {gap['rawLinks']} to {gap['renderedLinks']} after JavaScript")
    only_rendered_schema = [t for t in gap["renderedSchemaTypes"] if t not in gap["rawSchemaTypes"]]
    if only_rendered_schema:
        reasons.append("structured data only after JavaScript: " + ", ".join(only_rendered_schema[:5]))
    if gap["renderedH1"] and not gap["rawH1"]:
        reasons.append("the H1 appears only after JavaScript")
    return reasons


def screenshot_name(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()[:48] or "home"
    return f"{slug}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:6]}.jpg"


def build_findings(pages: list[dict]) -> list[dict]:
    findings: dict[str, dict] = {}

    def add(fid, tone, title, explanation, url, detail):
        finding = findings.setdefault(fid, {"id": fid, "category": "browser", "tone": tone, "title": title,
                                            "explanation": explanation, "targets": []})
        if len(finding["targets"]) < 200 and all(t["url"] != url for t in finding["targets"]):
            finding["targets"].append({"url": url, "detail": detail})

    for page in pages:
        url = page["url"]
        reasons = js_gap_reasons(page.get("jsGap"))
        if reasons:
            add("js-dependent-content", "review", "Content that depends on JavaScript",
                "A crawler that does not run JavaScript, which includes most AI crawlers, sees less of this page than a browser does. "
                "Measured by comparing the raw HTML with one rendered load.", url, "; ".join(reasons))
        lab = page.get("lab") or {}
        if lab.get("lcpMs", 0) > SLOW_LCP_MS:
            add("slow-lab-lcp", "review", "Slow largest paint in a lab load",
                f"The largest element painted after more than {SLOW_LCP_MS // 1000} seconds in one local lab load. "
                "This machine, the capture proxy and the network all affect it; confirm with field data before acting.",
                url, f"{lab['lcpMs']} ms")
        a11y = page.get("a11y") or {}
        for violation in a11y.get("violations") or []:
            add(f"a11y-{violation['id']}", "review", f"Accessibility: {violation['help']}",
                "axe-core reported this automated rule on a sampled page. Automated rules cover only part of WCAG, "
                "so manual review is still needed before claiming conformance.",
                url, f"{violation['impact']}, {violation['nodes']} element{'s' if violation['nodes'] != 1 else ''}")
        third = page.get("thirdParty") or {}
        hosts = third.get("hosts") or []
        if hosts:
            listed = ", ".join(f"{h['host']} ({h['category']})" for h in hosts[:8])
            more = f" and {len(hosts) - 8} more" if len(hosts) > 8 else ""
            add("third-party-before-interaction", "coverage", "Third parties contacted before any interaction",
                "These hosts were requested on first load before any click or consent choice. "
                "This is an observation for review, not a consent or legal assessment.", url, listed + more)
    return list(findings.values())


def _audit_one(browser, url, *, site_root, allow_url, allow_resource_url, raw_html, page_deadline, axe_source, host):
    entry = {"url": url, "screenshot": None, "lab": None, "jsGap": None,
             "a11y": {"state": "skipped", "engine": None, "violations": [], "passes": 0},
             "thirdParty": {"hosts": [], "cookies": [], "note": THIRD_PARTY_NOTE}, "error": None}

    def left():
        return max(0.5, page_deadline - time.monotonic())

    blocked: list[dict] = []
    requests_by_host: dict[str, dict] = {}
    request_count = 0
    context = browser.new_context(user_agent=DEFAULT_REQUEST_HEADERS["User-Agent"], viewport={"width": 1440, "height": 900},
                                  service_workers="block", bypass_csp=True)
    try:
        context.expose_binding("__webObsReportBlockedTransport",
                               lambda _source, kind, api: blocked.append({"resourceType": kind, "api": api}) if len(blocked) < 128 else None)
        context.add_init_script(script=_TRANSPORT_GUARD)
        context.add_init_script(script=_LAB_OBSERVER)
        context.route("**/*", make_safe_playwright_route_handler(
            {"media", "font"}, blocked_requests=blocked, max_duration_sec=left(),
            allow_url=allow_resource_url or allow_url, allow_document_url=allow_url))
        context.route_web_socket("**/*", lambda _socket: blocked.append({"resourceType": "websocket"}) if len(blocked) < 128 else None)
        page = context.new_page()

        def on_request(request):
            nonlocal request_count
            parsed = urlparse(request.url)
            if parsed.scheme not in ("http", "https"):
                return
            request_count += 1
            req_host = (parsed.hostname or "").lower()
            if req_host and not is_same_site_host(req_host, host):
                row = requests_by_host.setdefault(req_host, {"host": req_host, "requests": 0, "category": categorize_host(req_host)})
                row["requests"] += 1

        page.on("request", on_request)
        if allow_url is not None and not allow_url(url):
            entry["error"] = "Page refused by crawl policy."
            return entry
        page.goto(url, wait_until="load", timeout=left() * 1000)
        try:
            page.wait_for_load_state("networkidle", timeout=min(3000, left() * 1000))
        except Exception:
            pass
        if allow_url is not None and not allow_url(page.url):
            entry["error"] = "Final rendered URL refused by crawl policy."
            return entry
        lab = page.evaluate(_LAB_READ)
        lab.update(requests=request_count, note=LAB_NOTE)
        entry["lab"] = lab
        size = page.evaluate("() => new TextEncoder().encode(document.documentElement.outerHTML).byteLength")
        if size <= MAX_HTML_BYTES:
            entry["jsGap"] = js_gap(raw_html, page.content())
        try:
            shot = page.screenshot(type="jpeg", quality=70, full_page=False, timeout=min(10000, left() * 1000))
            name = screenshot_name(url)
            folder = Path(site_root) / "assets" / "screenshots"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(shot)
            entry["screenshot"] = f"assets/screenshots/{name}"
        except Exception:
            entry["screenshot"] = None
        cookies = []
        for cookie in context.cookies():
            domain = (cookie.get("domain") or "").lstrip(".").lower()
            cookies.append({"name": cookie.get("name", ""), "domain": cookie.get("domain", ""),
                            "firstParty": bool(domain) and is_same_site_host(domain, host),
                            "secure": bool(cookie.get("secure")), "httpOnly": bool(cookie.get("httpOnly")),
                            "sameSite": cookie.get("sameSite") or "None"})
        entry["thirdParty"] = {"hosts": sorted(requests_by_host.values(), key=lambda r: (-r["requests"], r["host"]))[:40],
                               "cookies": cookies[:60], "note": THIRD_PARTY_NOTE}
        if axe_source is None:
            entry["a11y"] = {"state": "skipped", "engine": None, "violations": [], "passes": 0,
                             "detail": "The bundled axe-core file is missing."}
        else:
            try:
                page.add_script_tag(content=axe_source)
                result = page.evaluate(_AXE_RUN, AXE_TAGS)
                if result.get("error"):
                    entry["a11y"] = {"state": "skipped", "engine": None, "violations": [], "passes": 0, "detail": result["error"]}
                else:
                    violations = sorted(result.get("violations") or [], key=lambda v: (-v["nodes"], v["id"]))[:40]
                    entry["a11y"] = {"state": "ok", "engine": f"axe-core {result.get('version')}",
                                     "violations": violations, "passes": int(result.get("passes") or 0)}
            except Exception as exc:
                entry["a11y"] = {"state": "skipped", "engine": None, "violations": [], "passes": 0,
                                 "detail": f"axe-core could not run: {type(exc).__name__}"}
        return entry
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else 'browser audit failed'}"
        return entry
    finally:
        try:
            context.close()
        except Exception:
            pass


def run_browser_audit(sample: Iterable[str], *, site_root: str, domain_folder: str,
                      allow_url: Optional[Callable[[str], bool]] = None,
                      allow_resource_url: Optional[Callable[[str], bool]] = None,
                      raw_html_by_url: Optional[dict] = None,
                      time_budget_sec: float = 90, per_page_sec: float = 25,
                      render_mode: str = "auto") -> dict:
    """Audit up to five sampled pages in one guarded headless browser. Never raises."""
    urls = []
    for url in sample or []:
        if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    urls = urls[:MAX_SAMPLE]
    if render_mode == "never":
        return _skipped("Browser rendering is turned off for this capture (Fast HTTP only).")
    if not urls:
        return _skipped("No healthy pages were available to sample.")
    if sync_playwright is None:
        return _skipped("Install Playwright and Chromium to enable the browser audit.")
    raw_html_by_url = raw_html_by_url or {}
    try:
        axe_source = AXE_PATH.read_text(encoding="utf-8")
    except OSError:
        axe_source = None
    started = time.monotonic()
    deadline = started + max(1.0, float(time_budget_sec))
    pages: list[dict] = []
    skipped_urls: list[str] = []
    driver = browser = None
    try:
        driver = sync_playwright().start()
        resolved = resolve_chromium_executable(driver)
        if not resolved.get("executablePath"):
            return _skipped(resolved.get("error") or "No compatible Chromium was found.")
        browser = driver.chromium.launch(headless=True, executable_path=resolved["executablePath"],
                                         timeout=30000, args=list(_BROWSER_TRANSPORT_ARGS))
        for url in urls:
            now = time.monotonic()
            if now >= deadline - 2:
                skipped_urls.append(url)
                continue
            host = (urlparse(url).hostname or "").lower()
            pages.append(_audit_one(browser, url, site_root=site_root, allow_url=allow_url,
                                    allow_resource_url=allow_resource_url, raw_html=raw_html_by_url.get(url),
                                    page_deadline=min(deadline, now + per_page_sec), axe_source=axe_source, host=host))
    except Exception as exc:
        if not pages:
            return _skipped(f"The browser could not start: {type(exc).__name__}.")
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if driver is not None:
                driver.stop()
        except Exception:
            pass
    failed = [p for p in pages if p.get("error")]
    complete = [p for p in pages if not p.get("error")]
    if not complete:
        state = "skipped"
        detail = "No sampled page could be audited in the browser."
    elif failed or skipped_urls:
        state = "partial"
        detail = f"Audited {len(complete)} of {len(urls)} sampled pages."
        if skipped_urls:
            detail += f" {len(skipped_urls)} skipped by the {int(time_budget_sec)} second budget."
    else:
        state = "ok"
        detail = f"Audited {len(complete)} sampled page{'s' if len(complete) != 1 else ''}."
    return {"state": state, "detail": detail, "elapsedSec": round(time.monotonic() - started, 2),
            "sampledUrls": urls, "budgetSkippedUrls": skipped_urls, "pages": pages,
            "findings": build_findings(complete)}
