#!/usr/bin/env python3
"""
URL safety and DNS-pinned HTTP fetching for web-obs.

Adapted from claude-seo's canonical SSRF protection layer:
- Blocks non-http(s) schemes, authority confusion, private/loopback/link-local
  addresses, RFC 6598 shared space, and cloud metadata endpoints.
- Pins DNS resolution during HTTP sessions to mitigate DNS rebinding.
- Supports explicit local staging/test origins via WEB_OBS_LOCAL_TARGETS
  (or CLAUDE_SEO_LOCAL_TARGETS) while keeping cloud metadata permanently blocked.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional
from urllib.parse import urlparse
from urllib.parse import urljoin
import uuid

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

__all__ = [
    "URLSafetyError",
    "is_safe_ip",
    "normalize_hostname",
    "validate_url",
    "validate_url_strict",
    "safe_requests_get",
    "safe_requests_session",
    "make_safe_playwright_route_handler",
    "decode_body",
    "decode_response_text",
    "DEFAULT_USER_AGENT",
    "DEFAULT_REQUEST_HEADERS",
    "request_context",
    "request_deadline",
    "RequestDeadlineExceeded",
]

_IPV4_OBFUSCATED_RE = re.compile(
    r"^(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}$",
    re.IGNORECASE,
)

_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata.goog",
        "metadata",
        "metadata.azure.com",
        "metadata.ec2.internal",
        "metadata.oraclecloud.com",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "169.254.169.254",
        "fd00:ec2::254",
    }
)

_NEVER_ALLOWLISTABLE_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata",
        "metadata.goog",
        "metadata.google.internal",
        "metadata.azure.com",
        "metadata.ec2.internal",
        "metadata.oraclecloud.com",
        "169.254.169.254",
        "100.100.100.200",
        "fd00:ec2::254",
        "0.0.0.0",
    }
)

_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 WebObs/0.1"
)

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

_CONTENT_TYPE_CHARSET_RE = re.compile(r"charset\s*=\s*['\"]?([^;,'\"\s>]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(
    r"<meta[^>]+charset\s*=\s*['\"]?([^;,'\"\s/>]+)",
    re.IGNORECASE,
)
_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

_request_context = threading.local()


class URLSafetyError(ValueError):
    """Raised when a URL fails SSRF safety checks."""


class RequestDeadlineExceeded(TimeoutError):
    """The current task exhausted its absolute request deadline."""


@contextmanager
def request_context(limiter=None, owner_id=None, deadline=None, allow_url=None):
    """Attach shared request leases to this execution thread without global DNS."""
    previous = getattr(_request_context, "value", None)
    _request_context.value = (limiter, owner_id or uuid.uuid4().hex, deadline, allow_url)
    try:
        yield
    finally:
        _request_context.value = previous


def request_deadline():
    value = getattr(_request_context, "value", None)
    return value[2] if value else None


@contextmanager
def request_policy_override(allow_url):
    """Use an explicit bootstrap policy while retaining the task lease/deadline."""
    previous = getattr(_request_context, "value", None)
    if previous:
        limiter, owner, deadline, _old_policy = previous
        with request_context(limiter, owner, deadline, allow_url):
            yield
    else:
        with request_context(allow_url=allow_url):
            yield


def check_request_deadline():
    deadline = request_deadline()
    if deadline is not None and time.monotonic() >= deadline:
        raise RequestDeadlineExceeded("Request deadline reached.")


def _request_lease(url):
    value = getattr(_request_context, "value", None)
    if not value or value[0] is None:
        return None, None
    limiter, owner, deadline, _policy = value
    while True:
        check_request_deadline()
        token = limiter.try_acquire(owner, url)
        if token:
            return limiter, token
        time.sleep(0.01)


def _raw_authority(url: str) -> str:
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]*)", url)
    return match.group(1) if match else ""


def _reject_authority_confusion(url: str, parsed) -> None:
    authority = _raw_authority(url)
    authority_lower = authority.lower()
    url_lower = url.lower()

    if "\\" in authority or "%5c" in authority_lower:
        raise URLSafetyError("URL authority contains a backslash")
    if "%" in authority:
        raise URLSafetyError("URL authority contains percent-encoding")
    if parsed.username is not None or parsed.password is not None or "@" in authority:
        raise URLSafetyError("URL userinfo is not allowed")
    if "#@" in url or "%23@" in url_lower:
        raise URLSafetyError("URL fragment/userinfo confusion refused")


def is_safe_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or (ip.version == 4 and ip in _SHARED_ADDRESS_SPACE)
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_allowlistable_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if str(ip) in _NEVER_ALLOWLISTABLE_HOSTNAMES:
        return False
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if ip.is_loopback:
        return True
    return not ip.is_reserved


def normalize_hostname(hostname: str) -> str:
    if not hostname:
        raise URLSafetyError("Empty hostname")
    h = hostname.lower().strip()
    if h.endswith(".") and not h.endswith(".."):
        h = h[:-1]
    if _IPV4_OBFUSCATED_RE.match(h):
        try:
            packed = socket.inet_aton(h)
        except OSError as exc:
            raise URLSafetyError(f"Malformed IPv4 obfuscation refused: {hostname!r}") from exc
        h = socket.inet_ntoa(packed)
    return h


def _parse_local_target(entry: str) -> Optional[tuple[str, Optional[int]]]:
    entry = entry.strip()
    if not entry:
        return None
    if entry.count(":") > 1 and "[" not in entry:
        candidate, port = entry, None
    else:
        try:
            parsed = urlparse(f"//{entry}")
            candidate, port = parsed.hostname, parsed.port
        except ValueError:
            return None
        if not candidate:
            return None
    try:
        return normalize_hostname(candidate), port
    except URLSafetyError:
        return None


def _local_targets() -> tuple[tuple[str, Optional[int]], ...]:
    parts: list[str] = []
    for env_key in ("WEB_OBS_LOCAL_TARGETS", "CLAUDE_SEO_LOCAL_TARGETS"):
        raw = os.environ.get(env_key, "")
        if raw.strip():
            parts.extend(raw.split(","))
    if not parts:
        return ()
    parsed = (_parse_local_target(part) for part in parts)
    return tuple(entry for entry in parsed if entry is not None)


def _looks_like_ip(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _is_allowlisted_local_target(hostname: str, port: Optional[int]) -> bool:
    if hostname in _NEVER_ALLOWLISTABLE_HOSTNAMES:
        return False
    if not _is_allowlistable_ip(hostname) and _looks_like_ip(hostname):
        return False
    for entry_host, entry_port in _local_targets():
        if entry_host != hostname:
            continue
        if entry_port is None or entry_port == port:
            return True
    return False


def _url_port(parsed) -> Optional[int]:
    try:
        explicit = parsed.port
    except ValueError:
        return None
    if explicit is not None:
        return explicit
    return 443 if parsed.scheme == "https" else 80


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        _reject_authority_confusion(url, parsed)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        hostname = normalize_hostname(parsed.hostname)
    except URLSafetyError:
        return False

    port = _url_port(parsed)
    allowlisted = port is not None and _is_allowlisted_local_target(hostname, port)
    if hostname in _BLOCKED_HOSTNAMES and not allowlisted:
        return False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return True
    if is_safe_ip(hostname):
        return True
    return allowlisted and _is_allowlistable_ip(hostname)


def validate_url_strict(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    _reject_authority_confusion(url, parsed)
    if parsed.scheme not in ("http", "https"):
        raise URLSafetyError(f"Invalid URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise URLSafetyError("URL has no hostname")

    hostname = normalize_hostname(parsed.hostname)
    port = _url_port(parsed)
    if port is None:
        raise URLSafetyError(f"Invalid port in URL authority: {url!r}")

    allowlisted = _is_allowlisted_local_target(hostname, port)
    if hostname in _BLOCKED_HOSTNAMES and not allowlisted:
        raise URLSafetyError(f"Blocked hostname: {hostname}")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if not is_safe_ip(hostname) and not (allowlisted and _is_allowlistable_ip(hostname)):
            raise URLSafetyError(f"Blocked IP literal: {hostname}")
        return url, str(literal)

    try:
        addrinfo = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, UnicodeError) as exc:
        raise URLSafetyError(f"DNS resolution failed for {hostname}: {exc}") from exc

    resolved_ips = sorted({info[4][0] for info in addrinfo}, key=lambda value: (":" in value, value))
    if not resolved_ips:
        raise URLSafetyError(f"No address records for {hostname}")

    for ip_str in resolved_ips:
        if is_safe_ip(ip_str):
            continue
        if allowlisted and _is_allowlistable_ip(ip_str):
            continue
        raise URLSafetyError(
            f"DNS rebinding refused: {hostname} resolves to non-public IP {ip_str}"
        )

    return url, resolved_ips[0]


class _PinnedAdapter(HTTPAdapter):
    """Keep the original HTTP/TLS host while connecting to its validated IP."""
    def __init__(self, pinned_ip):
        self.pinned_ip = pinned_ip
        super().__init__(pool_connections=4, pool_maxsize=2, max_retries=0)

    def init_poolmanager(self, *args, **kwargs):
        pinned_ip = self.pinned_ip
        def connect(connection):
            family = socket.AF_INET6 if ":" in pinned_ip else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(connection.timeout)
                for option in connection.socket_options or []:
                    sock.setsockopt(*option)
                if connection.source_address:
                    sock.bind(connection.source_address)
                address = (pinned_ip, connection.port, 0, 0) if family == socket.AF_INET6 else (pinned_ip, connection.port)
                sock.connect(address)
                return sock
            except socket.timeout as exc:
                sock.close()
                raise ConnectTimeoutError(connection, "Pinned connection timed out.") from exc
            except OSError as exc:
                sock.close()
                raise NewConnectionError(connection, "Pinned connection failed.") from exc
        class PinnedHTTP(HTTPConnection):
            _new_conn = connect
        class PinnedHTTPS(HTTPSConnection):
            _new_conn = connect
        class HTTPPool(HTTPConnectionPool):
            ConnectionCls = PinnedHTTP
        class HTTPSPool(HTTPSConnectionPool):
            ConnectionCls = PinnedHTTPS
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": HTTPPool, "https": HTTPSPool}


class _SafeSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False
        self._active_responses = []
        self._pins = {}
        self._current_adapter = None

    def get_adapter(self, url):
        if self._current_adapter is None:
            raise URLSafetyError("A validated connection adapter is required.")
        return self._current_adapter

    def request(self, method, url, **kwargs):
        if method.upper() not in ("GET", "HEAD"):
            raise URLSafetyError("Only GET and HEAD requests are permitted.")
        if self.proxies or kwargs.get("proxies"):
            raise URLSafetyError("Proxies are not permitted for pinned requests.")
        redirects = kwargs.pop("allow_redirects", True)
        history = []
        current = url
        for hop in range(6):
            check_request_deadline()
            context = getattr(_request_context, "value", None)
            if context and context[3] is not None and not context[3](current):
                raise URLSafetyError("Request refused by crawl policy.")
            limiter, lease = _request_lease(current)
            try:
                norm, pinned_ip = validate_url_strict(current)
                check_request_deadline()
                parsed = urlparse(norm)
                origin = f"{parsed.scheme}://{parsed.netloc}/"
                if self._pins.get(origin) != pinned_ip:
                    old = self.adapters.get(origin)
                    if old:
                        old.close()
                    self.mount(origin, _PinnedAdapter(pinned_ip))
                    self._pins[origin] = pinned_ip
                self._current_adapter = self.adapters[origin]
                options = dict(kwargs)
                deadline = request_deadline()
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RequestDeadlineExceeded("Request deadline reached.")
                    configured = options.get("timeout")
                    connect, read = configured if isinstance(configured, tuple) else (configured, configured)
                    options["timeout"] = tuple(min(value, remaining / 2) if isinstance(value, (float, int)) else remaining / 2 for value in (connect, read))
                response = super().request(method, norm, allow_redirects=False, **options)
            except BaseException:
                if lease:
                    limiter.release(lease)
                raise
            original_close = response.close
            released = [False]
            def close(original_close=original_close, released=released, limiter=limiter, lease=lease):
                try:
                    original_close()
                finally:
                    if lease and not released[0]:
                        released[0] = True
                        limiter.release(lease)
            response.close = close
            self._active_responses.append(response)
            response.history = list(history)
            if not redirects or response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            response.close()
            history.append(response)
            if hop == 5:
                raise requests.TooManyRedirects("More than five redirects.")
            current = urljoin(norm, location)
        raise requests.TooManyRedirects("More than five redirects.")

    def close(self):
        try:
            for response in self._active_responses:
                response.close()
            self._active_responses.clear()
        finally:
            super().close()


def _decode_bytes(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def decode_body(raw: bytes, content_type: str = "") -> str:
    raw = raw or b""
    for marker, encoding in _BOMS:
        if raw.startswith(marker):
            return _decode_bytes(raw[len(marker) :], encoding.replace("-sig", ""))

    match = _CONTENT_TYPE_CHARSET_RE.search(content_type or "")
    if match:
        return _decode_bytes(raw, match.group(1).strip())

    head = raw[:4096].decode("ascii", errors="ignore")
    meta_match = _META_CHARSET_RE.search(head)
    if meta_match:
        return _decode_bytes(raw, meta_match.group(1).strip())

    return raw.decode("utf-8", errors="replace")


def decode_response_text(response) -> str:
    content_type = response.headers.get("Content-Type", "") if response.headers else ""
    return decode_body(response.content or b"", content_type)


def safe_requests_get(url: str, *, timeout: int = 25, **kwargs) -> requests.Response:
    """Compatibility convenience; prefer a scoped session for streamed responses."""
    session = _SafeSession()
    try:
        headers = dict(DEFAULT_REQUEST_HEADERS)
        headers.update(kwargs.pop("headers", {}) or {})
        response = session.get(url, timeout=timeout, headers=headers, **kwargs)
        original_close = response.close
        def close():
            # Avoid re-entering this wrapper when the session closes its responses.
            response.close = original_close
            session.close()
        response.close = close
        return response
    except BaseException:
        session.close()
        raise


@contextmanager
def safe_requests_session(url: str) -> Iterator[requests.Session]:
    # Validate the syntax here; actual DNS and leases are scoped to each request.
    if not validate_url(url):
        raise URLSafetyError("Invalid or blocked request URL.")
    session = _SafeSession()
    try:
        yield session
    finally:
        session.close()


def make_safe_playwright_route_handler(
    blocked_resource_types: Optional[set[str]] = None,
    *,
    max_response_bytes: int = 5 * 1024 * 1024,
    max_requests: int = 128,
    max_duration_sec: float = 25,
    max_total_bytes: int = 20 * 1024 * 1024,
    blocked_requests: Optional[list[dict]] = None,
    allow_url=None,
    allow_document_url=None,
):
    """Render public documents and static assets through the pinned HTTP client.

    Background data APIs, form submissions, beacons and event streams are outside
    the capture contract. Browser redirects are refused because Chromium can
    follow fulfilled redirects without interception. HTTP routes are fulfilled
    only with a bounded, non-redirect response from the pinned client.
    """
    blocked = set(blocked_resource_types or ())
    allowed = {"document", "stylesheet", "script", "image", "font", "media"}
    remaining = max_requests
    deadline = time.monotonic() + max_duration_sec
    remaining_bytes = max_total_bytes

    def refuse(route, request, reason):
        if blocked_requests is not None and len(blocked_requests) < max_requests:
            blocked_requests.append({"resourceType": request.resource_type, "reason": reason})
        route.abort()

    def handler(route, request):
        nonlocal remaining, remaining_bytes
        try:
            if request.resource_type not in allowed or request.resource_type in blocked:
                refuse(route, request, "Background data or excluded resource type")
                return
            if request.method.upper() not in {"GET", "HEAD"}:
                refuse(route, request, "Only read-only GET and HEAD are permitted")
                return
            parsed = urlparse(request.url)
            if parsed.scheme not in ("http", "https"):
                if parsed.scheme in ("data", "blob", "about"):
                    route.continue_()
                else:
                    refuse(route, request, "Unsupported resource scheme")
                return
            remaining -= 1
            if remaining < 0:
                refuse(route, request, "Rendering request budget reached")
                return
            policy = allow_document_url if request.resource_type == "document" and allow_document_url is not None else allow_url
            if policy is not None and not policy(request.url):
                refuse(route, request, "Resource refused by crawl policy")
                return
            time_left = deadline - time.monotonic()
            if time_left <= 0 or remaining_bytes <= 0:
                refuse(route, request, "Rendering time or byte budget reached")
                return
            with safe_requests_session(request.url) as session:
                response = session.request(
                    request.method,
                    request.url,
                    headers={**DEFAULT_REQUEST_HEADERS, "Accept": request.headers.get("accept", "*/*")},
                    timeout=max(0.01, min(15, deadline - time.monotonic())),
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if 300 <= response.status_code < 400 and response.status_code != 304:
                        refuse(route, request, "Browser redirects are disabled")
                        return
                    chunks = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=65536):
                        size += len(chunk)
                        remaining_bytes -= len(chunk)
                        if time.monotonic() >= deadline or remaining_bytes < 0:
                            refuse(route, request, "Rendering time or byte budget reached")
                            return
                        if size > max_response_bytes:
                            refuse(route, request, "Rendering response exceeded byte limit")
                            return
                        chunks.append(chunk)
                    # requests decodes compressed bodies; do not reapply encoding or stale sizes.
                    excluded = {
                        "content-encoding", "content-length", "transfer-encoding",
                        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                        "te", "trailer", "upgrade", "set-cookie",
                    }
                    headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded}
                    route.fulfill(status=response.status_code, headers=headers, body=b"".join(chunks))
                finally:
                    response.close()
        except Exception:
            try:
                refuse(route, request, "Resource could not be fetched safely")
            except Exception:
                pass

    return handler
