#!/usr/bin/env python3
"""TLS, header quality and email DNS checks, using local fixtures only.

The TLS tests run a local HTTPS server with a freshly generated self-signed
certificate. DNS parsing is tested with record strings and a fake resolver, so no
public DNS query is made.
"""
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import transport_checks as tc


class HeaderQualityTests(unittest.TestCase):
    def test_split_set_cookie_keeps_expires_dates_whole(self):
        folded = ("sid=abc; Path=/; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Secure; HttpOnly, "
                  "theme=dark; Max-Age=60, _ga=GA1.2.3; SameSite=None")
        parts = tc.split_set_cookie(folded)
        self.assertEqual([p.split("=", 1)[0] for p in parts], ["sid", "theme", "_ga"])
        self.assertIn("Expires=Wed, 21 Oct 2026 07:28:00 GMT", parts[0])
        self.assertEqual(tc.split_set_cookie(""), [])

    def test_set_cookie_values_prefers_raw_list(self):
        class Raw:
            class headers:
                @staticmethod
                def getlist(name):
                    return ["a=1; Secure", "b=2"] if name == "Set-Cookie" else []
        class Response:
            raw = Raw()
            headers = {"Set-Cookie": "a=1; Secure, b=2"}
        self.assertEqual(tc.set_cookie_values(Response()), ["a=1; Secure", "b=2"])
        self.assertEqual(tc.set_cookie_values({"set-cookie": "a=1, b=2; Path=/"}), ["a=1", "b=2; Path=/"])
        self.assertEqual(tc.set_cookie_values({}), [])

    def test_strong_headers_have_no_issues(self):
        headers = {
            "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'nonce-r4nd'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff", "Server": "nginx",
        }
        result = tc.analyze_header_quality(headers, ["sid=1; Secure; HttpOnly; SameSite=Lax"])
        self.assertTrue(result["hsts"]["preloadReady"])
        self.assertEqual(result["hsts"]["issues"], [])
        self.assertEqual(result["csp"]["issues"], [])
        self.assertEqual(result["cookies"][0]["issues"], [])
        self.assertEqual(result["otherIssues"], [])

    def test_weak_headers_are_explained(self):
        headers = {
            "strict-transport-security": "max-age=300",
            "content-security-policy-report-only": "script-src * 'unsafe-inline' 'unsafe-eval'",
            "x-powered-by": "PHP/7.4.3", "server": "Apache/2.4.41 (Ubuntu)",
            "x-frame-options": "ALLOW-FROM https://x", "referrer-policy": "unsafe-url",
            "access-control-allow-origin": "*", "access-control-allow-credentials": "true",
        }
        result = tc.analyze_header_quality(headers, ["track=1; SameSite=None", "pref=2"])
        self.assertIn("max-age is below one year.", result["hsts"]["issues"])
        self.assertIn("includeSubDomains is not set.", result["hsts"]["issues"])
        self.assertFalse(result["hsts"]["preloadReady"])
        self.assertTrue(result["csp"]["reportOnly"])
        joined = " ".join(result["csp"]["issues"])
        for fragment in ("report-only", "'unsafe-inline'", "'unsafe-eval'", "* in script-src", "object-src", "base-uri", "frame-ancestors"):
            self.assertIn(fragment, joined)
        self.assertIn("SameSite=None without Secure is rejected by browsers.", result["cookies"][0]["issues"])
        self.assertIn("No SameSite attribute; browsers default to Lax.", result["cookies"][1]["issues"])
        other = " ".join(result["otherIssues"])
        for fragment in ("x-powered-by", "server discloses", "X-Frame-Options", "unsafe-url", "credentials"):
            self.assertIn(fragment, other)

    def test_missing_headers_and_nonce_exemption(self):
        result = tc.analyze_header_quality({}, [])
        self.assertFalse(result["hsts"]["present"])
        self.assertIn("Content-Security-Policy was not sent.", result["csp"]["issues"])
        nonce = tc.analyze_header_quality({"Content-Security-Policy": "script-src 'unsafe-inline' 'nonce-x'"})
        self.assertFalse(any("unsafe-inline" in issue for issue in nonce["csp"]["issues"]))
        http_site = tc.analyze_header_quality({}, ["a=1; HttpOnly; SameSite=Lax"], https=False)
        self.assertEqual(http_site["hsts"]["issues"], [])
        self.assertEqual(http_site["cookies"][0]["issues"], [])
        self.assertEqual(tc.analyze_header_quality(None, None)["cookies"], [])


class EmailParsingTests(unittest.TestCase):
    def test_spf(self):
        good = tc.parse_spf(["google-site-verification=x", "v=spf1 include:_spf.google.com ~all"])
        self.assertEqual(good["allQualifier"], "~")
        self.assertEqual(good["lookupCount"], 1)
        self.assertEqual(good["issues"], [])
        self.assertIn("+all lets any server send mail for this domain.", tc.parse_spf(["v=spf1 +all"])["issues"])
        self.assertIn("No all mechanism at the end of the record.", tc.parse_spf(["v=spf1 mx"])["issues"])
        self.assertEqual(tc.parse_spf(["v=spf1 redirect=_spf.example.com"])["issues"], [])
        many = tc.parse_spf(["v=spf1 " + " ".join(f"include:s{i}.example.com" for i in range(11)) + " ptr -all"])
        self.assertTrue(any("allows 10" in i for i in many["issues"]))
        self.assertTrue(any("ptr" in i for i in many["issues"]))
        self.assertIn("More than one SPF record, which makes SPF invalid.", tc.parse_spf(["v=spf1 -all", "v=spf1 ~all"])["issues"])
        self.assertFalse(tc.parse_spf([])["present"])

    def test_dmarc(self):
        strict = tc.parse_dmarc(["v=DMARC1; p=reject; rua=mailto:d@example.com"])
        self.assertEqual((strict["policy"], strict["rua"], strict["issues"]), ("reject", True, []))
        loose = tc.parse_dmarc(["v=DMARC1; p=none; pct=50"])
        self.assertEqual(loose["pct"], 50)
        self.assertEqual(len(loose["issues"]), 3)
        self.assertIn("No DMARC record.", tc.parse_dmarc([])["issues"])

    def test_email_dns_with_fake_resolver(self):
        class Rdata:
            def __init__(self, text):
                self.strings = [text.encode()]
        class Mx:
            preference, exchange = 10, "mx.example.com."
        class Caa:
            def to_text(self):
                return '0 issue "letsencrypt.org"'
        records = {
            ("example.com", "MX"): [Mx()],
            ("example.com", "TXT"): [Rdata("v=spf1 include:_spf.example.net -all")],
            ("_dmarc.example.com", "TXT"): [Rdata("v=DMARC1; p=quarantine; rua=mailto:r@example.com")],
            ("google._domainkey.example.com", "TXT"): [Rdata("v=DKIM1; k=rsa; p=MIGf")],
            ("example.com", "CAA"): [Caa()],
        }
        class Resolver:
            def resolve(self, name, kind):
                if (name, kind) not in records:
                    raise tc.DNSNoRecord(name)
                return records[(name, kind)]
        result = tc.check_email_dns("www.example.com", resolver=Resolver())
        self.assertEqual(result["state"], "ok", result["detail"])
        self.assertEqual(result["domain"], "example.com")
        self.assertEqual(result["mx"], ["10 mx.example.com"])
        self.assertEqual(result["dkim"]["found"], ["google"])
        self.assertEqual(result["caa"], ['0 issue "letsencrypt.org"'])
        self.assertEqual(tc.transport_findings({}, {}, result, "https://example.com/"), [])

        records.pop(("example.com", "TXT"))
        records.pop(("_dmarc.example.com", "TXT"))
        bare = tc.check_email_dns("example.com", resolver=Resolver())
        self.assertEqual(bare["state"], "fail")
        ids = {f["id"] for f in tc.transport_findings({}, {}, bare, "https://example.com/")}
        self.assertTrue({"spf-missing", "dmarc-missing"} <= ids)

        class Slow:
            def resolve(self, name, kind):
                raise tc.DNSTimeout()
        self.assertEqual(tc.check_email_dns("example.com", resolver=Slow())["state"], "unreachable")

    def test_email_dns_skips_cleanly(self):
        self.assertEqual(tc.check_email_dns("127.0.0.1", resolver=object())["state"], "skipped")
        if tc.dns is None:
            skipped = tc.check_email_dns("example.com")
            self.assertEqual(skipped["state"], "skipped")
            self.assertIn("dnspython", skipped["detail"])
            self.assertEqual(tc.transport_findings(None, None, skipped, "https://example.com/"), [])


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed to generate a local test certificate")
class TlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cert = os.path.join(cls.tmp.name, "cert.pem")
        cls.key = os.path.join(cls.tmp.name, "key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", cls.key, "-out", cls.cert,
                        "-days", "10", "-subj", "/CN=127.0.0.1/O=Web-Obs Fixture",
                        "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"],
                       check=True, capture_output=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.cert, cls.key)
        cls.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.listener.bind(("127.0.0.1", 0))
        cls.listener.listen(8)
        cls.port = cls.listener.getsockname()[1]
        cls.stop = False

        def serve():
            while not cls.stop:
                try:
                    conn, _ = cls.listener.accept()
                except OSError:
                    return
                try:
                    with context.wrap_socket(conn, server_side=True) as tls:
                        tls.recv(1)
                except (ssl.SSLError, OSError):
                    pass
        cls.thread = threading.Thread(target=serve, daemon=True)
        cls.thread.start()
        cls.previous_targets = os.environ.get("WEB_OBS_LOCAL_TARGETS")
        os.environ["WEB_OBS_LOCAL_TARGETS"] = f"127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.stop = True
        cls.listener.close()
        if cls.previous_targets is None:
            os.environ.pop("WEB_OBS_LOCAL_TARGETS", None)
        else:
            os.environ["WEB_OBS_LOCAL_TARGETS"] = cls.previous_targets
        cls.tmp.cleanup()

    def test_self_signed_certificate_fails_verification(self):
        result = tc.check_tls_certificate(f"https://127.0.0.1:{self.port}")
        self.assertEqual(result["state"], "fail")
        self.assertFalse(result["verified"])
        self.assertTrue(result["error"])
        ids = [f["id"] for f in tc.transport_findings(result, None, None, "https://127.0.0.1/")]
        self.assertEqual(ids, ["tls-not-verified"])

    def test_trusted_certificate_reports_expiry_window(self):
        result = tc.check_tls_certificate(f"https://127.0.0.1:{self.port}", cafile=self.cert)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["state"], "warn")
        self.assertIn(result["daysRemaining"], (9, 10))
        self.assertIn(result["tlsVersion"], ("TLSv1.2", "TLSv1.3"))
        self.assertIn("127.0.0.1", result["san"])
        self.assertIsNone(result["coversWww"])
        self.assertIn("Web-Obs Fixture", result["issuer"])
        findings = tc.transport_findings(result, None, None, "https://127.0.0.1/")
        self.assertEqual([f["id"] for f in findings], ["tls-expiring"])
        self.assertEqual(findings[0]["category"], "security")

    def test_refusals_never_raise(self):
        self.assertEqual(tc.check_tls_certificate("http://example.com")["state"], "skipped")
        self.assertEqual(tc.check_tls_certificate("https://10.0.0.1")["state"], "unreachable")
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        os.environ["WEB_OBS_LOCAL_TARGETS"] = f"127.0.0.1:{self.port},127.0.0.1:{port}"
        self.assertEqual(tc.check_tls_certificate(f"https://127.0.0.1:{port}", timeout=1)["state"], "unreachable")

    def test_alternate_host_matching(self):
        self.assertTrue(tc._name_matches("*.example.com", "www.example.com"))
        self.assertFalse(tc._name_matches("*.example.com", "example.com"))
        self.assertFalse(tc._name_matches("*.example.com", "a.b.example.com"))
        self.assertEqual(tc._alternate_host("www.example.com"), "example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
