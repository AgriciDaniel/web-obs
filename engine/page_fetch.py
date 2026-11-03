"""Bounded HTTP and browser fetching with explicit page and asset policies."""
from __future__ import annotations

import hashlib
import copy
import re
import time
from urllib.parse import urljoin

import requests
from browser_runtime import resolve_chromium_executable
from resources import classify_resource
from url_safety import (DEFAULT_REQUEST_HEADERS, RequestDeadlineExceeded, URLSafetyError,
                        decode_body, make_safe_playwright_route_handler,
                        request_context, request_deadline, safe_requests_session)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

MAX_HTML_BYTES = 5 * 1024 * 1024
_BROWSER_TRANSPORT_ARGS = [
    '--disable-quic',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
]
_TRANSPORT_GUARD = r"""
(() => {
    const notify = globalThis.__webObsReportBlockedTransport;
    const reported = new Set();
    for (const [name, kind] of [
        ['RTCPeerConnection', 'webrtc'],
        ['webkitRTCPeerConnection', 'webrtc'],
        ['WebTransport', 'webtransport'],
        ['Worker', 'worker'],
        ['SharedWorker', 'worker'],
    ]) {
        const BlockedTransport = class {
            constructor() {
                if (!reported.has(name)) {
                    reported.add(name);
                    if (typeof notify === 'function') {
                        try { Promise.resolve(notify(kind, name)).catch(() => {}); } catch (_) {}
                    }
                }
                throw new DOMException('Direct browser transports are disabled during capture.', 'NotSupportedError');
            }
        };
        Object.defineProperty(BlockedTransport, '__webObsTransportGuard', { value: true });
        Object.defineProperty(globalThis, name, {
            value: BlockedTransport, writable: false, configurable: false,
        });
    }
})();
"""
_SPA_SHELL_MARKERS = ('<div id="root"></div>', '<div id="__next"></div>',
                      '<div id="app"></div>', '<div id="__nuxt"></div>',
                      'you need to enable javascript', 'please enable javascript')


def _looks_like_spa_shell(html):
    lower = html.lower()
    if not html or not any(marker in lower for marker in _SPA_SHELL_MARKERS):
        return False
    cleaned = re.sub(r'<(script|style|noscript)\b[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    visible = re.sub(r'<[^>]+>', ' ', cleaned)
    return len(re.sub(r'\s+', ' ', visible).strip()) < 280


def _empty(url):
    return {'requested_url': url, 'final_url': url, 'status_code': None,
            'content_type': '', 'content_disposition': '', 'headers': {},
            'response_time_ms': 0, 'ttfb_ms': 0, 'fetch_duration_ms': 0, 'redirect_hops': 0, 'html_bytes': 0, 'raw_sha256': '',
            'raw_bytes': b'', 'raw_kind': 'http-response-decoded', 'html': '',
            'redirect_chain': [], 'blocked_requests': [], 'render_used': False,
            'is_spa': False, 'resource_type': 'page', 'state': 'pending',
            'error': None, 'error_kind': None}


def _failed(result, kind, message):
    result.update(state='error', error_kind=kind, error=message)
    return result


class PageFetcher:
    """One owner thread/process, one reusable browser, isolated context per task."""
    def __init__(self):
        self._playwright = None
        self._browser = None

    def _browser_instance(self, timeout_ms=30000):
        if sync_playwright is None:
            raise RuntimeError('Playwright is not available in the selected environment.')
        if self._browser is not None and not self._browser.is_connected():
            self.close()
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._browser is None:
            resolved = resolve_chromium_executable(self._playwright)
            if not resolved['executablePath']:
                raise RuntimeError(resolved['error'])
            self._browser = self._playwright.chromium.launch(
                headless=True, executable_path=resolved['executablePath'], timeout=timeout_ms,
                args=list(_BROWSER_TRANSPORT_ARGS))
        return self._browser

    def close(self):
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            self._browser = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None

    def fetch(self, url, render_mode='auto', timeout_sec=25,
              allow_url=None, allow_resource_url=None, prior_http=None):
        result = _empty(url)
        if prior_http is not None:
            result.update({key: copy.deepcopy(value) for key, value in prior_http.items() if key in result})
            result.update(requested_url=url, error=None, error_kind=None, state='pending')
        started = time.monotonic()
        hop_started = None
        inherited = request_deadline()
        deadline = min(inherited, started + timeout_sec) if inherited is not None else started + timeout_sec
        def remaining():
            left = deadline - time.monotonic()
            if left <= 0:
                raise RequestDeadlineExceeded('Page deadline reached.')
            return left
        def allowed(target):
            return allow_url is None or allow_url(target)
        try:
            if not allowed(url):
                return _failed(result, 'policy', 'Page refused by crawl policy.')
            if render_mode != 'always' and prior_http is None:
                current = url
                visited = set()
                for hop in range(6):
                    remaining()
                    if current in visited:
                        return _failed(result, 'redirect', 'Page redirect loop.')
                    visited.add(current)
                    if not allowed(current):
                        return _failed(result, 'policy', 'Page redirect refused by crawl policy.')
                    hop_started = time.monotonic()
                    with safe_requests_session(current) as session:
                        response = session.get(current, headers=dict(DEFAULT_REQUEST_HEADERS),
                                               timeout=max(.001, remaining() / 2),
                                               allow_redirects=False, stream=True)
                        result['ttfb_ms'] = int(round((time.monotonic() - hop_started) * 1000))
                        try:
                            remaining()
                            result.update(final_url=current, status_code=response.status_code,
                                          headers=dict(response.headers),
                                          content_type=response.headers.get('Content-Type', ''),
                                          content_disposition=response.headers.get('Content-Disposition', ''))
                            if response.status_code in (301, 302, 303, 307, 308):
                                location = response.headers.get('Location')
                                if not location or hop == 5:
                                    return _failed(result, 'redirect', 'Page redirect has no target or exceeds five hops.')
                                result['redirect_chain'].append({'url': current, 'status_code': response.status_code})
                                current = urljoin(current, location)
                                continue
                            classification = classify_resource(current, result['content_type'], result['content_disposition'])
                            result['resource_type'] = classification['type']
                            if classification['type'] != 'page':
                                # The asset lane decides download policy and byte limits.
                                result.update(state='resource', error=None, error_kind=None)
                                return result
                            chunks, size = [], 0
                            for chunk in response.iter_content(chunk_size=8192):
                                remaining()
                                size += len(chunk)
                                if size > MAX_HTML_BYTES:
                                    return _failed(result, 'size', 'HTML response exceeded the 5 MB capture limit.')
                                chunks.append(chunk)
                            raw = b''.join(chunks)
                            result.update(raw_bytes=raw, raw_sha256=hashlib.sha256(raw).hexdigest(),
                                          html_bytes=len(raw), html=decode_body(raw, result['content_type']))
                            result['is_spa'] = _looks_like_spa_shell(result['html'])
                            break
                        finally:
                            response.close()
                if render_mode == 'never' or (render_mode == 'auto' and not result['is_spa']):
                    result['state'] = 'complete'
                    return result
            context = None
            try:
                browser = self._browser_instance(remaining() * 1000)
                remaining()
                context = browser.new_context(user_agent=DEFAULT_REQUEST_HEADERS['User-Agent'],
                                              viewport={'width': 1440, 'height': 900}, service_workers='block')
                def report_transport(_source, kind, api_name):
                    apis = {'RTCPeerConnection': 'webrtc', 'webkitRTCPeerConnection': 'webrtc',
                            'WebTransport': 'webtransport', 'Worker': 'worker', 'SharedWorker': 'worker'}
                    if apis.get(api_name) == kind and len(result['blocked_requests']) < 128:
                        result['blocked_requests'].append({
                            'resourceType': kind,
                            'api': api_name,
                            'reason': 'Background browser workers are disabled during capture.' if kind == 'worker' else 'Direct browser transport is disabled during capture.',
                        })
                context.expose_binding('__webObsReportBlockedTransport', report_transport)
                context.add_init_script(script=_TRANSPORT_GUARD)
                context.route('**/*', make_safe_playwright_route_handler(
                    {'media', 'font'}, blocked_requests=result['blocked_requests'],
                    max_duration_sec=remaining(), allow_url=allow_resource_url or allow_url,
                    allow_document_url=allow_url))
                def block_socket(_socket):
                    if len(result['blocked_requests']) < 128:
                        result['blocked_requests'].append({'resourceType': 'websocket', 'reason': 'Background connections are disabled'})
                context.route_web_socket('**/*', block_socket)
                page = context.new_page()
                if not page.evaluate("""() => ['RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport', 'Worker', 'SharedWorker'].every(
                    name => globalThis[name].__webObsTransportGuard === true &&
                            Object.getOwnPropertyDescriptor(globalThis, name).configurable === false
                )"""):
                    return _failed(result, 'policy', 'Browser transport guards could not be installed.')
                target = result['final_url'] if prior_http is not None or render_mode == 'auto' else url
                if not allowed(target):
                    return _failed(result, 'policy', 'Render target refused by crawl policy.')
                response = page.goto(target, wait_until='networkidle', timeout=remaining() * 1000)
                remaining()
                if not allowed(page.url):
                    return _failed(result, 'policy', 'Final rendered URL refused by crawl policy.')
                if response is not None:
                    result.update(status_code=response.status, headers=dict(response.headers),
                                  content_type=response.headers.get('content-type', 'text/html'),
                                  content_disposition=response.headers.get('content-disposition', ''))
                result['resource_type'] = classify_resource(page.url, result['content_type'], result['content_disposition'])['type']
                if result['resource_type'] != 'page':
                    result.update(final_url=page.url, state='resource')
                    return result
                # Check in the browser before copying a possibly huge string over IPC.
                size = page.evaluate('() => new TextEncoder().encode(document.documentElement.outerHTML).byteLength')
                remaining()
                if size > MAX_HTML_BYTES:
                    return _failed(result, 'size', 'Rendered HTML exceeded the 5 MB capture limit.')
                html = page.content()
                raw = html.encode('utf-8', errors='replace')
                if len(raw) > MAX_HTML_BYTES:
                    return _failed(result, 'size', 'Rendered HTML exceeded the 5 MB capture limit.')
                remaining()
                result.update(final_url=page.url, html=html, html_bytes=len(raw), raw_bytes=raw,
                              raw_sha256=hashlib.sha256(raw).hexdigest(), raw_kind='rendered-dom',
                              render_used=True, state='complete', error=None, error_kind=None)
                return result
            finally:
                if context is not None:
                    context.close()
        except (RequestDeadlineExceeded, requests.Timeout) as exc:
            return _failed(result, 'timeout', str(exc))
        except URLSafetyError as exc:
            return _failed(result, 'safety', str(exc))
        except Exception as exc:
            policy_refusal = any(row.get('resourceType') == 'document' and 'policy' in row.get('reason', '') for row in result['blocked_requests'])
            kind = 'policy' if policy_refusal else 'timeout' if 'timeout' in type(exc).__name__.lower() else 'fetch'
            return _failed(result, kind, str(exc))
        finally:
            now = time.monotonic()
            # fetch_duration_ms covers every redirect hop. response_time_ms is the final request
            # alone, from connection to the last body byte, so a redirect no longer inflates it.
            result['fetch_duration_ms'] = int(round((now - started) * 1000))
            result['redirect_hops'] = len(result['redirect_chain'])
            if result.get('render_used') or hop_started is None:
                result['response_time_ms'] = result['fetch_duration_ms']
            else:
                result['response_time_ms'] = int(round((now - hop_started) * 1000))


def fetch_page_html(url, render_mode='auto', timeout_sec=25, allow_url=None,
                    allow_resource_url=None, prior_http=None):
    fetcher = PageFetcher()
    try:
        return fetcher.fetch(url, render_mode, timeout_sec, allow_url, allow_resource_url, prior_http)
    finally:
        fetcher.close()
