"""Full-page snapshots: one rendered screenshot per page, plus the rendered HTML on request.

Each snapshot is one guarded headless load through the same browser routes the capture uses,
so robots rules, the crawl policy, Crawl-delay pacing and the WebObs user agent all apply.
Snapshots are capped by page count, image height and a total time budget so a large site does
not turn a capture into hours of rendering or a vault full of images.

The page is photographed beyond the viewport at the normal 1280 x 800 window, the way a full-page
screenshot works in Chromium. The window is never resized to the page height: sections sized in
viewport units (a 100vh hero) would grow with it, inflate the page and push the rest past the cap.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from browser_runtime import resolve_chromium_executable
from page_fetch import MAX_HTML_BYTES, _BROWSER_TRANSPORT_ARGS, _TRANSPORT_GUARD
from url_safety import DEFAULT_REQUEST_HEADERS, make_safe_playwright_route_handler

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Optional: snapshots report themselves as skipped.
    sync_playwright = None

DEFAULT_LIMIT = 25
VIEWPORT = {"width": 1280, "height": 800}
MAX_HEIGHT_PX = 24000
JPEG_QUALITY = 60
SNAPSHOT_DIR = "assets/screenshots"
HTML_DIR = "assets/snapshots"

# Scroll once through the page so lazy images load, then return to the top. Scrolling is forced to
# be instant: with `scroll-behavior: smooth` (common) a jump becomes a slow glide, the steps never reach
# their positions and the picture is taken part way down, with pinned headers drawn mid-page. The
# script waits until the page really is back at the top.
_SCROLL_THROUGH = """async (maxHeight) => {
  for (const el of [document.documentElement, document.body]) if (el) el.style.setProperty('scroll-behavior', 'auto', 'important');
  const jump = (y) => window.scrollTo({ top: y, left: 0, behavior: 'instant' });
  const pause = (ms) => new Promise(r => setTimeout(r, ms));
  const step = Math.max(400, window.innerHeight);
  const end = Math.min(document.documentElement.scrollHeight, maxHeight);
  for (let y = 0; y < end; y += step) { jump(y); await pause(250); }
  jump(document.documentElement.scrollHeight);
  await pause(250);
  jump(0);
  for (let i = 0; i < 20 && (window.scrollY !== 0 || window.scrollX !== 0); i++) { await pause(50); jump(0); }
  await pause(400);
  return document.documentElement.scrollHeight;
}"""


# Scroll-linked effects (GSAP, Framer and similar) write inline opacity and transforms that depend on
# the viewport. Elements caught part way through such an effect are shown in their resting state.
# An element at opacity 0 is settled only when it also carries an offset and sits in normal page flow,
# which is the waiting state of a scroll reveal. Menus, dialogs and slides hidden on purpose are
# usually fixed or absolutely positioned, or hidden with display or visibility, and stay hidden.
_SETTLE_MOTION = """() => {
  let settled = 0;
  for (const el of document.querySelectorAll('[style]')) {
    const st = el.style;
    const op = st.opacity === '' ? 1 : parseFloat(st.opacity);
    const moved = (st.transform && st.transform !== 'none') || (st.translate && st.translate !== 'none');
    let settle = (op > 0.01 && op < 0.99) || (moved && op > 0.01);
    if (!settle && moved && op <= 0.01) {
      const cs = getComputedStyle(el);
      settle = cs.display !== 'none' && cs.visibility !== 'hidden' && (cs.position === 'static' || cs.position === 'relative');
    }
    if (settle) { el.setAttribute('data-web-obs-settle', ''); settled++; }
  }
  if (settled) {
    const css = document.createElement('style');
    css.textContent = '[data-web-obs-settle]{opacity:1!important;transform:none!important;translate:none!important;scale:none!important;rotate:none!important}';
    document.head.appendChild(css);
  }
  return settled;
}"""


# Elements pinned to the lower part of the window (cookie banners, chat bubbles, back-to-top buttons)
# would land over the top of a full-page picture, so they are hidden for the snapshot only. Pinned
# headers, and anything starting in the top 40% of the window, stay. Sticky elements stay too: they
# sit in the page flow and belong where they are.
_HIDE_FLOATING = """() => {
  const limit = window.innerHeight * 0.4;
  let hidden = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' || cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.top < limit) continue;
    el.setAttribute('data-web-obs-hide', ''); hidden++;
  }
  if (!hidden) return 0;
  const host = document.head || document.documentElement;
  if (!host) return 0;
  const css = document.createElement('style');
  css.textContent = '[data-web-obs-hide]{visibility:hidden!important}';
  host.appendChild(css);
  return hidden;
}"""


def snapshot_name(url: str, suffix: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()[:48] or "home"
    return f"full-{slug}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:6]}.{suffix}"


def _skipped(detail: str) -> dict:
    return {"state": "skipped", "detail": detail, "pages": {}, "limit": 0}


def _snapshot_one(browser, url: str, *, site_root: str, allow_url, allow_resource_url, deadline: float, save_html: bool) -> dict:
    entry = {"url": url, "screenshot": None, "html": None, "heightPx": None, "truncated": False, "error": None,
             "method": "beyond-viewport", "capPx": MAX_HEIGHT_PX}

    def left() -> float:
        return max(0.5, deadline - time.monotonic())

    blocked: list[dict] = []
    context = browser.new_context(user_agent=DEFAULT_REQUEST_HEADERS["User-Agent"], viewport=VIEWPORT,
                                  service_workers="block")
    try:
        context.expose_binding("__webObsReportBlockedTransport",
                               lambda _source, kind, api: blocked.append({"resourceType": kind, "api": api}) if len(blocked) < 128 else None)
        context.add_init_script(script=_TRANSPORT_GUARD)
        context.route("**/*", make_safe_playwright_route_handler(
            {"media"}, blocked_requests=blocked, max_duration_sec=left(),
            allow_url=allow_resource_url or allow_url, allow_document_url=allow_url))
        context.route_web_socket("**/*", lambda _socket: blocked.append({"resourceType": "websocket"}) if len(blocked) < 128 else None)
        page = context.new_page()
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
        try:
            height = int(page.evaluate(_SCROLL_THROUGH, MAX_HEIGHT_PX) or 0)
        except Exception:
            height = int(page.evaluate("() => document.documentElement.scrollHeight") or 0)
        height = max(VIEWPORT["height"], height)
        shot_height = min(height, MAX_HEIGHT_PX)
        try:
            page.evaluate(_SETTLE_MOTION)
        except Exception:
            pass
        try:
            entry["hiddenOverlays"] = int(page.evaluate(_HIDE_FLOATING) or 0)
        except Exception:
            entry["hiddenOverlays"] = 0
        page.wait_for_timeout(200)
        try:
            entry["scrollY"] = int(page.evaluate("() => { window.scrollTo({ top: 0, left: 0, behavior: 'instant' }); return window.scrollY; }") or 0)
        except Exception:
            entry["scrollY"] = None
        # Beyond the viewport, at scroll 0, with the window left at its normal size. Finished CSS
        # animations show their end state (on-scroll reveals, typing effects).
        image = page.screenshot(type="jpeg", quality=JPEG_QUALITY, full_page=True, animations="disabled",
                                clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": shot_height},
                                timeout=min(15000, left() * 1000))
        folder = Path(site_root) / SNAPSHOT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        name = snapshot_name(url, "jpg")
        (folder / name).write_bytes(image)
        entry.update(screenshot=f"{SNAPSHOT_DIR}/{name}", heightPx=height, truncated=height > MAX_HEIGHT_PX, bytes=len(image))
        if save_html:
            html = page.content()
            raw = html.encode("utf-8", errors="replace")
            if len(raw) <= MAX_HTML_BYTES:
                html_folder = Path(site_root) / HTML_DIR
                html_folder.mkdir(parents=True, exist_ok=True)
                html_name = snapshot_name(url, "html")
                (html_folder / html_name).write_bytes(raw)
                entry["html"] = f"{HTML_DIR}/{html_name}"
        return entry
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else 'snapshot failed'}"
        return entry
    finally:
        try:
            context.close()
        except Exception:
            pass


def run_page_snapshots(urls: Iterable[str], *, site_root: str, limit: int = DEFAULT_LIMIT, save_html: bool = False,
                       allow_url: Optional[Callable[[str], bool]] = None,
                       allow_resource_url: Optional[Callable[[str], bool]] = None,
                       time_budget_sec: float = 240, per_page_sec: float = 25, render_mode: str = "auto") -> dict:
    """Snapshot up to `limit` pages, in the order given (most important first). Never raises."""
    ordered: list[str] = []
    for url in urls or []:
        if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in ordered:
            ordered.append(url)
    limit = max(0, int(limit or 0))
    if limit == 0:
        return _skipped("Page snapshots are turned off for this capture.")
    if render_mode == "never":
        return _skipped("Browser rendering is turned off for this capture (Fast HTTP only).")
    if not ordered:
        return _skipped("No healthy pages were available to snapshot.")
    if sync_playwright is None:
        return _skipped("Install Playwright and Chromium to enable page snapshots.")
    chosen, not_chosen = ordered[:limit], ordered[limit:]
    started = time.monotonic()
    deadline = started + max(1.0, float(time_budget_sec))
    pages: dict[str, dict] = {}
    budget_skipped: list[str] = []
    driver = browser = None
    try:
        driver = sync_playwright().start()
        resolved = resolve_chromium_executable(driver)
        if not resolved.get("executablePath"):
            return _skipped(resolved.get("error") or "No compatible Chromium was found.")
        browser = driver.chromium.launch(headless=True, executable_path=resolved["executablePath"],
                                         timeout=30000, args=list(_BROWSER_TRANSPORT_ARGS))
        for url in chosen:
            now = time.monotonic()
            if now >= deadline - 2:
                budget_skipped.append(url)
                continue
            pages[url] = _snapshot_one(browser, url, site_root=site_root, allow_url=allow_url,
                                       allow_resource_url=allow_resource_url,
                                       deadline=min(deadline, now + per_page_sec), save_html=save_html)
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
    done = [p for p in pages.values() if p.get("screenshot")]
    detail = f"Saved {len(done)} full-page snapshot{'s' if len(done) != 1 else ''}."
    if not_chosen:
        detail += f" {len(not_chosen)} more pages were left out by the limit of {limit}."
    if budget_skipped:
        detail += f" {len(budget_skipped)} skipped by the {int(time_budget_sec)} second budget."
    failed = len(pages) - len(done)
    if failed:
        detail += f" {failed} could not be rendered."
    # The page limit is a setting, not a failure; only the time budget and render errors make it partial.
    state = "ok" if done and not (budget_skipped or failed) else ("partial" if done else "skipped")
    return {"state": state, "detail": detail, "elapsedSec": round(time.monotonic() - started, 2), "limit": limit,
            "pages": pages, "notChosen": len(not_chosen), "budgetSkipped": budget_skipped,
            "note": (f"Rendered once at {VIEWPORT['width']} px wide, beyond the {VIEWPORT['height']} px window. Images are cut at "
                     f"{MAX_HEIGHT_PX:,} px tall. Banners pinned to the bottom of the window are hidden.")}
