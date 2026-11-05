"""TLS certificate, response header quality and email DNS observations.

Every entry point returns a plain dict and never raises. The TLS check opens one
socket to the validated public address of the target site. The header analysis is
pure parsing of headers the capture already received. The email DNS check is
optional (dnspython) and queries the system DNS resolver, which is the only part of
this module that contacts anything other than the target website.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from url_safety import URLSafetyError, normalize_hostname, validate_url_strict


class DNSNoRecord(Exception):
    """Raised by test resolvers for a name with no records of the requested type."""


class DNSTimeout(Exception):
    """Raised by test resolvers for a query that timed out."""


try:  # Optional: email DNS checks are skipped when dnspython is not installed.
    import dns.exception
    import dns.resolver
    _NO_RECORD = (DNSNoRecord, dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers)
    _TIMEOUT = (DNSTimeout, dns.exception.Timeout)
except ImportError:  # pragma: no cover - exercised when the package is absent
    dns = None
    _NO_RECORD = (DNSNoRecord,)
    _TIMEOUT = (DNSTimeout,)

TLS_WARN_DAYS = 21
DKIM_COMMON_SELECTORS = ("google", "default", "selector1", "selector2", "k1", "s1", "mail", "dkim")
_ONE_YEAR = 31536000
_VERSION_DISCLOSURE_RE = re.compile(r"[A-Za-z][\w.-]*/\d+(?:\.\d+)+")


def _skipped(detail: str, **extra) -> dict:
    return {"state": "skipped", "detail": detail, **extra}


def _lower_headers(headers) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


# TLS certificate

def _name_matches(pattern: str, host: str) -> bool:
    pattern, host = pattern.lower().rstrip("."), host.lower().rstrip(".")
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host.endswith(suffix) and host.count(".") == pattern.count(".")
    return pattern == host


def _alternate_host(host: str) -> str:
    return host[4:] if host.startswith("www.") else f"www.{host}"


def _cert_names(cert: dict) -> list[str]:
    return [value for kind, value in cert.get("subjectAltName", ()) if kind in ("DNS", "IP Address")]


def _dn_text(dn) -> str:
    parts = []
    for rdn in dn or ():
        for key, value in rdn:
            if key in ("commonName", "organizationName"):
                parts.append(value)
    return ", ".join(dict.fromkeys(parts))


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def check_tls_certificate(origin: str, timeout: float = 6.0, *, cafile: Optional[str] = None,
                          now: Optional[float] = None) -> dict:
    """Read the target's certificate over one verified TLS handshake.

    `cafile` exists for local tests. Real captures use the system trust store.
    """
    base = {"issuer": None, "subject": None, "notBefore": None, "notAfter": None, "daysRemaining": None,
            "tlsVersion": None, "san": [], "coversWww": None, "verified": False, "error": None}
    try:
        parsed = urlparse(origin)
        if parsed.scheme != "https":
            return {**base, **_skipped("The site was captured over HTTP, so no certificate was read.")}
        host = normalize_hostname(parsed.hostname or "")
        port = parsed.port or 443
        _url, pinned_ip = validate_url_strict(f"https://{parsed.netloc}/")
    except URLSafetyError as exc:
        return {**base, "state": "unreachable", "detail": "Host does not resolve to a permitted public address.", "error": str(exc)}
    except Exception as exc:  # malformed origin
        return {**base, "state": "unreachable", "detail": "The site address could not be parsed.", "error": str(exc)}

    context = ssl.create_default_context(cafile=cafile)
    family = socket.AF_INET6 if ":" in pinned_ip else socket.AF_INET
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError as exc:
        return {**base, "state": "unreachable", "detail": "No network route for this address family.", "error": str(exc)}
    sock.settimeout(timeout)
    try:
        sock.connect((pinned_ip, port))
        with context.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert() or {}
            version = tls.version()
    except ssl.SSLCertVerificationError as exc:
        sock.close()
        reason = getattr(exc, "verify_message", "") or str(exc)
        return {**base, "state": "fail", "detail": f"The certificate did not verify: {reason}.", "error": reason}
    except (ssl.SSLError, OSError) as exc:
        sock.close()
        return {**base, "state": "unreachable", "detail": "The TLS handshake did not complete.", "error": str(exc)}

    current = time.time() if now is None else now
    result = {**base, "verified": True, "tlsVersion": version, "san": _cert_names(cert)[:50],
              "issuer": _dn_text(cert.get("issuer")), "subject": _dn_text(cert.get("subject"))}
    try:
        not_after = ssl.cert_time_to_seconds(cert["notAfter"])
        not_before = ssl.cert_time_to_seconds(cert["notBefore"])
        result.update(notAfter=_iso(not_after), notBefore=_iso(not_before),
                      daysRemaining=int((not_after - current) // 86400))
    except (KeyError, ValueError):
        pass
    if not host.replace(".", "").isdigit() and ":" not in host:
        alternate = _alternate_host(host)
        result["coversWww"] = any(_name_matches(name, alternate) for name in result["san"])
    problems = []
    state = "ok"
    days = result["daysRemaining"]
    if days is not None and days < 0:
        state = "fail"
        problems.append("The certificate has expired.")
    elif days is not None and days < TLS_WARN_DAYS:
        state = "warn"
        problems.append(f"The certificate expires in {days} day{'s' if days != 1 else ''}.")
    if version in ("TLSv1", "TLSv1.1", "SSLv3"):
        state = "warn" if state == "ok" else state
        problems.append(f"The server negotiated {version}; TLS 1.2 or newer is expected.")
    result["state"] = state
    result["detail"] = " ".join(problems) or f"Verified certificate from {result['issuer'] or 'an unnamed issuer'}, {days} days remaining."
    return result


# Header quality

def split_set_cookie(value: str) -> list[str]:
    """Split a comma-folded Set-Cookie header without breaking Expires dates."""
    if not value:
        return []
    parts = re.split(r",\s*(?=[^;,=\s]+=[^;,]*)", value)
    return [part.strip() for part in parts if part.strip()]


def set_cookie_values(source) -> list[str]:
    """Raw Set-Cookie values from a requests Response, urllib3 headers, or a plain dict."""
    raw = getattr(source, "raw", None)
    raw_headers = getattr(raw, "headers", None) if raw is not None else None
    for candidate in (raw_headers, source):
        getlist = getattr(candidate, "getlist", None)
        if callable(getlist):
            try:
                values = [str(v) for v in getlist("Set-Cookie")]
            except Exception:
                values = []
            if values:
                return values
    headers = getattr(source, "headers", source)
    if isinstance(headers, dict) or hasattr(headers, "items"):
        for key, value in headers.items():
            if str(key).lower() == "set-cookie":
                return split_set_cookie(str(value))
    return []


def _parse_cookie(value: str, https: bool) -> dict:
    pieces = [p.strip() for p in value.split(";")]
    name = pieces[0].split("=", 1)[0].strip() if pieces and pieces[0] else ""
    attrs = {}
    for piece in pieces[1:]:
        key, _sep, val = piece.partition("=")
        attrs[key.strip().lower()] = val.strip()
    same_site = attrs.get("samesite")
    cookie = {"name": name[:80], "secure": "secure" in attrs, "httpOnly": "httponly" in attrs,
              "sameSite": same_site.capitalize() if same_site else None, "issues": []}
    if https and not cookie["secure"]:
        cookie["issues"].append("Missing Secure on an HTTPS site.")
    if not cookie["httpOnly"]:
        cookie["issues"].append("Missing HttpOnly; fine only if scripts must read this cookie.")
    if same_site is None:
        cookie["issues"].append("No SameSite attribute; browsers default to Lax.")
    elif same_site.lower() == "none" and not cookie["secure"]:
        cookie["issues"].append("SameSite=None without Secure is rejected by browsers.")
    return cookie


def _parse_csp(value: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for chunk in value.split(";"):
        tokens = chunk.strip().split()
        if tokens:
            directives.setdefault(tokens[0].lower(), [t for t in tokens[1:]])
    return directives


def _csp_issues(directives: dict[str, list[str]]) -> list[str]:
    issues = []
    script_name = "script-src" if "script-src" in directives else "default-src" if "default-src" in directives else None
    if script_name is None:
        issues.append("No script-src or default-src, so scripts are unrestricted.")
    else:
        sources = [s.lower() for s in directives[script_name]]
        has_nonce_or_hash = any(s.startswith(("'nonce-", "'sha256-", "'sha384-", "'sha512-")) for s in sources)
        if "'unsafe-inline'" in sources and not has_nonce_or_hash:
            issues.append(f"'unsafe-inline' in {script_name}.")
        if "'unsafe-eval'" in sources:
            issues.append(f"'unsafe-eval' in {script_name}.")
        for loose in ("*", "https:", "http:", "data:"):
            if loose in sources:
                issues.append(f"{loose} in {script_name} allows scripts from almost anywhere.")
    if "object-src" not in directives and [s.lower() for s in directives.get("default-src", [])] != ["'none'"]:
        issues.append("No object-src restriction.")
    if "base-uri" not in directives:
        issues.append("No base-uri restriction.")
    if "frame-ancestors" not in directives:
        issues.append("No frame-ancestors; clickjacking protection relies on X-Frame-Options.")
    return issues


def analyze_header_quality(headers: dict, set_cookie_values: Optional[list[str]] = None, *, https: bool = True) -> dict:
    """Judge the content of security headers already received. Makes no requests."""
    try:
        low = _lower_headers(headers)
        hsts_raw = low.get("strict-transport-security")
        hsts = {"present": hsts_raw is not None, "maxAge": None, "includeSubDomains": False, "preload": False,
                "preloadReady": False, "issues": []}
        if hsts_raw is None:
            if https:
                hsts["issues"].append("Strict-Transport-Security was not sent.")
        else:
            match = re.search(r"max-age\s*=\s*\"?(\d+)", hsts_raw, re.I)
            hsts["maxAge"] = int(match.group(1)) if match else None
            hsts["includeSubDomains"] = bool(re.search(r"includesubdomains", hsts_raw, re.I))
            hsts["preload"] = bool(re.search(r"\bpreload\b", hsts_raw, re.I))
            if hsts["maxAge"] is None:
                hsts["issues"].append("max-age is missing, so the header is ignored.")
            elif hsts["maxAge"] == 0:
                hsts["issues"].append("max-age=0 switches HSTS off.")
            elif hsts["maxAge"] < _ONE_YEAR:
                hsts["issues"].append("max-age is below one year.")
            if not hsts["includeSubDomains"]:
                hsts["issues"].append("includeSubDomains is not set.")
            hsts["preloadReady"] = bool(hsts["maxAge"] and hsts["maxAge"] >= _ONE_YEAR and hsts["includeSubDomains"] and hsts["preload"])

        enforced = low.get("content-security-policy")
        report_only = low.get("content-security-policy-report-only")
        csp = {"present": enforced is not None, "reportOnly": enforced is None and report_only is not None,
               "directives": {}, "issues": []}
        policy = enforced if enforced is not None else report_only
        if policy is None:
            csp["issues"].append("Content-Security-Policy was not sent.")
        else:
            csp["directives"] = {k: v[:20] for k, v in list(_parse_csp(policy).items())[:30]}
            csp["issues"].extend(_csp_issues(csp["directives"]))
            if csp["reportOnly"]:
                csp["issues"].insert(0, "Only a report-only policy was sent, so nothing is enforced.")

        cookies = [_parse_cookie(v, https) for v in (set_cookie_values or [])[:40] if v.strip()]

        other = []
        nosniff = low.get("x-content-type-options")
        if nosniff is not None and nosniff.strip().lower() != "nosniff":
            other.append(f"X-Content-Type-Options is '{nosniff[:40]}', expected 'nosniff'.")
        xfo = low.get("x-frame-options")
        if xfo is not None and xfo.strip().upper() not in ("DENY", "SAMEORIGIN"):
            other.append(f"X-Frame-Options value '{xfo[:40]}' is not DENY or SAMEORIGIN.")
        referrer = (low.get("referrer-policy") or "").lower()
        if "unsafe-url" in referrer:
            other.append("Referrer-Policy unsafe-url sends full URLs to every destination.")
        for name in ("server", "x-powered-by", "x-aspnet-version", "x-generator"):
            value = low.get(name)
            if value and (name != "server" or _VERSION_DISCLOSURE_RE.search(value)):
                other.append(f"{name} discloses '{value[:60]}'.")
        if low.get("access-control-allow-origin", "").strip() == "*" and low.get("access-control-allow-credentials", "").lower() == "true":
            other.append("Access-Control-Allow-Origin * is combined with credentials.")
        return {"hsts": hsts, "csp": csp, "cookies": cookies, "otherIssues": other}
    except Exception as exc:  # never break a capture on malformed headers
        return {"hsts": None, "csp": None, "cookies": [], "otherIssues": [], "error": str(exc)}


# Email DNS

def parse_spf(records: list[str]) -> dict:
    spf = [r for r in records if r.strip().lower().startswith("v=spf1")]
    result = {"present": bool(spf), "record": spf[0] if spf else None, "allQualifier": None,
              "lookupCount": 0, "issues": []}
    if not spf:
        result["issues"].append("No SPF record.")
        return result
    if len(spf) > 1:
        result["issues"].append("More than one SPF record, which makes SPF invalid.")
    terms = spf[0].split()[1:]
    for term in terms:
        low = term.lower()
        bare = low.lstrip("+-~?")
        if bare == "all":
            result["allQualifier"] = low[0] if low[0] in "+-~?" else "+"
        if bare.split(":", 1)[0].split("/", 1)[0] in ("include", "a", "mx", "ptr", "exists") or low.startswith("redirect="):
            result["lookupCount"] += 1
        if bare.startswith("ptr"):
            result["issues"].append("The ptr mechanism is deprecated.")
    qualifier = result["allQualifier"]
    if qualifier == "+":
        result["issues"].append("+all lets any server send mail for this domain.")
    elif qualifier == "?":
        result["issues"].append("?all is neutral and gives receivers no guidance.")
    elif qualifier is None and not any(t.lower().startswith("redirect=") for t in terms):
        result["issues"].append("No all mechanism at the end of the record.")
    if result["lookupCount"] > 10:
        result["issues"].append(f"About {result['lookupCount']} DNS lookups at the top level; SPF allows 10.")
    return result


def parse_dmarc(records: list[str]) -> dict:
    dmarc = [r for r in records if r.strip().lower().startswith("v=dmarc1")]
    result = {"present": bool(dmarc), "record": dmarc[0] if dmarc else None, "policy": None,
              "subdomainPolicy": None, "pct": None, "rua": False, "issues": []}
    if not dmarc:
        result["issues"].append("No DMARC record.")
        return result
    if len(dmarc) > 1:
        result["issues"].append("More than one DMARC record, which makes DMARC invalid.")
    tags = {}
    for part in dmarc[0].split(";"):
        key, _sep, value = part.strip().partition("=")
        if key:
            tags[key.strip().lower()] = value.strip()
    result["policy"] = tags.get("p", "").lower() or None
    result["subdomainPolicy"] = tags.get("sp", "").lower() or None
    result["rua"] = bool(tags.get("rua"))
    try:
        result["pct"] = int(tags["pct"]) if "pct" in tags else None
    except ValueError:
        result["pct"] = None
    if result["policy"] is None:
        result["issues"].append("The record has no p= policy.")
    elif result["policy"] == "none":
        result["issues"].append("p=none only monitors; it does not protect against spoofing.")
    if not result["rua"]:
        result["issues"].append("No rua address, so no aggregate reports are requested.")
    if result["pct"] is not None and result["pct"] < 100:
        result["issues"].append(f"pct={result['pct']} applies the policy to part of the mail only.")
    return result


def _txt(resolver, name: str) -> list[str]:
    try:
        answer = resolver.resolve(name, "TXT")
    except _NO_RECORD:
        return []
    values = []
    for rdata in answer:
        values.append(b"".join(rdata.strings).decode("utf-8", errors="replace"))
    return values


class _BudgetedResolver:
    """Gives each query the shorter of its own timeout and the time left in a total budget."""

    def __init__(self, inner, timeout: float, budget_sec: float):
        self.inner, self.timeout = inner, timeout
        self.end = time.monotonic() + max(0.0, budget_sec)

    def resolve(self, name, rdtype):
        left = self.end - time.monotonic()
        if left <= 0.05:
            raise DNSTimeout("The DNS time budget was used up.")
        if hasattr(self.inner, "lifetime"):
            self.inner.lifetime = self.inner.timeout = min(self.timeout, left)
        return self.inner.resolve(name, rdtype)


def check_email_dns(domain: str, timeout: float = 4.0, *, resolver=None, budget_sec: Optional[float] = None) -> dict:
    """MX, SPF, DMARC, common DKIM selectors and CAA through the system resolver.

    `budget_sec` caps the whole check (about a dozen queries), for a capture with an overall deadline.
    """
    note = "Queried through the system DNS resolver."
    empty = {"mx": [], "spf": None, "dmarc": None, "dkim": {"checkedSelectors": [], "found": [], "note": "Common selectors only."},
             "caa": [], "note": note}
    if dns is None and resolver is None:
        return {**empty, **_skipped("Install dnspython to enable email DNS checks.")}
    try:
        host = normalize_hostname(domain).removeprefix("www.")
    except URLSafetyError:
        return {**empty, **_skipped("No domain name to check.")}
    if not host or re.fullmatch(r"[\d.]+", host) or ":" in host or "." not in host:
        return {**empty, **_skipped("Email DNS applies to domain names, not addresses.")}
    try:
        if resolver is None:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = timeout
            resolver.timeout = timeout
        if budget_sec is not None:
            resolver = _BudgetedResolver(resolver, timeout, budget_sec)
        result = dict(empty)
        try:
            mx_answer = resolver.resolve(host, "MX")
            result["mx"] = sorted(f"{r.preference} {str(r.exchange).rstrip('.')}" for r in mx_answer)[:20]
        except _NO_RECORD:
            result["mx"] = []
        result["spf"] = parse_spf(_txt(resolver, host))
        result["dmarc"] = parse_dmarc(_txt(resolver, f"_dmarc.{host}"))
        found = []
        for selector in DKIM_COMMON_SELECTORS:
            if any("p=" in record.lower() for record in _txt(resolver, f"{selector}._domainkey.{host}")):
                found.append(selector)
        result["dkim"] = {"checkedSelectors": list(DKIM_COMMON_SELECTORS), "found": found,
                          "note": "Common selectors only. A missing result does not mean DKIM is absent."}
        caa_name = host
        for _ in range(2):
            try:
                result["caa"] = sorted(r.to_text() for r in resolver.resolve(caa_name, "CAA"))[:20]
            except _NO_RECORD:
                result["caa"] = []
            if result["caa"] or caa_name.count(".") < 2:
                break
            caa_name = caa_name.split(".", 1)[1]
        issues = list(result["spf"]["issues"]) + list(result["dmarc"]["issues"])
        if result["mx"] and not result["spf"]["present"] and not result["dmarc"]["present"]:
            state = "fail"
        elif issues:
            state = "warn"
        else:
            state = "ok"
        if not result["mx"]:
            lead = "No MX records. If the domain sends no mail, publish SPF -all and DMARC p=reject."
        else:
            lead = f"{len(result['mx'])} MX record{'s' if len(result['mx']) != 1 else ''}."
        result["state"] = state
        result["detail"] = " ".join([lead, *issues[:3]])
        result["domain"] = host
        return result
    except _TIMEOUT:
        return {**empty, "state": "unreachable", "detail": "DNS queries timed out."}
    except Exception as exc:
        return {**empty, "state": "unreachable", "detail": "DNS queries failed.", "error": str(exc)[:200]}


# Findings

def _finding(fid: str, tone: str, title: str, explanation: str, targets: list[dict]) -> dict:
    return {"id": fid, "category": "security", "tone": tone, "title": title, "explanation": explanation, "targets": targets[:200]}


def transport_findings(tls: Optional[dict], headers_quality: Optional[dict], email_dns: Optional[dict], home_url: str) -> list[dict]:
    findings: list[dict] = []
    target = lambda detail: {"url": home_url, "detail": detail}  # noqa: E731
    tls = tls or {}
    if tls.get("state") == "fail" and not tls.get("verified"):
        findings.append(_finding("tls-not-verified", "attention", "The TLS certificate did not verify",
            "Browsers show a warning for this certificate. Check the chain, hostname and expiry with your host.",
            [target(tls.get("error") or tls.get("detail", ""))]))
    days = tls.get("daysRemaining")
    if isinstance(days, int) and days < TLS_WARN_DAYS:
        findings.append(_finding("tls-expiring", "attention" if days < 7 else "review",
            "The TLS certificate expires soon" if days >= 0 else "The TLS certificate has expired",
            "Renew the certificate or confirm that automatic renewal is working.",
            [target(f"{days} days remaining, expires {tls.get('notAfter')}")]))
    if tls.get("tlsVersion") in ("TLSv1", "TLSv1.1", "SSLv3"):
        findings.append(_finding("tls-old-version", "review", "An old TLS version was negotiated",
            "The server chose a protocol version older than TLS 1.2. Modern clients may refuse it.", [target(tls["tlsVersion"])]))
    if tls.get("coversWww") is False:
        findings.append(_finding("tls-alternate-host", "review", "The certificate does not cover the www or bare host",
            "Visitors typing the other form of the address may see a certificate error. Ignore this if that host is not used.",
            [target(", ".join(tls.get("san") or [])[:200])]))
    hq = headers_quality or {}
    hsts = hq.get("hsts") or {}
    if hsts.get("present") and hsts.get("issues"):
        findings.append(_finding("hsts-weak", "review", "HSTS is sent but weak",
            "The header exists but its settings limit the protection it gives.", [target(" ".join(hsts["issues"]))]))
    csp = hq.get("csp") or {}
    if (csp.get("present") or csp.get("reportOnly")) and csp.get("issues"):
        findings.append(_finding("csp-weak", "review", "The Content Security Policy has gaps",
            "These directives leave room for injected scripts. Tighten them step by step and test the site.",
            [target(issue) for issue in csp["issues"]]))
    flagged = [c for c in hq.get("cookies") or [] if any("Secure" in i or "SameSite=None" in i for i in c.get("issues", []))]
    if flagged:
        findings.append(_finding("cookie-flags", "review", "Cookies are missing protective flags",
            "Cookies set on the homepage response lack Secure or a valid SameSite setting.",
            [{"url": home_url, "detail": f"{c['name']}: {' '.join(c['issues'])}"} for c in flagged]))
    if hq.get("otherIssues"):
        findings.append(_finding("header-hygiene", "review", "Response headers disclose or misconfigure details",
            "Version strings help attackers pick exploits, and invalid values are ignored by browsers.",
            [target(issue) for issue in hq["otherIssues"]]))
    mail = email_dns or {}
    if mail.get("state") in ("ok", "warn", "fail"):
        spf, dmarc = mail.get("spf") or {}, mail.get("dmarc") or {}
        if not spf.get("present"):
            findings.append(_finding("spf-missing", "attention" if mail.get("mx") else "review", "No SPF record",
                "Without SPF, receivers cannot tell which servers may send mail for this domain.", [target(mail.get("domain", ""))]))
        elif spf.get("issues"):
            findings.append(_finding("spf-weak", "review", "The SPF record needs attention",
                "The record exists but is permissive or close to the lookup limit.", [target(i) for i in spf["issues"]]))
        if not dmarc.get("present"):
            findings.append(_finding("dmarc-missing", "attention" if mail.get("mx") else "review", "No DMARC record",
                "DMARC tells receivers what to do with spoofed mail and where to send reports.", [target(f"_dmarc.{mail.get('domain', '')}")]))
        elif dmarc.get("issues"):
            findings.append(_finding("dmarc-weak", "review", "The DMARC policy is not enforcing",
                "A monitoring-only or partial policy lets spoofed mail through.", [target(i) for i in dmarc["issues"]]))
        if mail.get("mx") and not (mail.get("dkim") or {}).get("found"):
            findings.append(_finding("dkim-not-found", "coverage", "No DKIM key at common selectors",
                "Only common selector names were checked. Your provider may use another selector.",
                [target(", ".join(DKIM_COMMON_SELECTORS))]))
        if not mail.get("caa"):
            findings.append(_finding("caa-missing", "review", "No CAA record",
                "A CAA record limits which certificate authorities may issue certificates for the domain.", [target(mail.get("domain", ""))]))
    return findings
