"""Every capture switch takes effect and produces a manifest the app can open.

Each case runs a loopback capture with one switch changed, asserts the change that switch must
make in the manifest, and passes the saved _site-graph.json through the app's own
parseSiteManifest (src/data/validateManifest.ts, bundled with esbuild), the same check the
Obsidian plugin and the standalone app run before showing a capture. A link recheck of a saved
capture is checked the same way.

A switch that cannot run here is reported as not exercisable, with the reason, and is not counted
as passed: the browser cases need a Chromium that starts, the TLS case needs openssl for a test
certificate authority, email DNS needs dnspython and a dotted domain name (loopback has none), and
--spell-check needs pyspellchecker. Offline: every server is on 127.0.0.1.
"""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import multiprocessing.process
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))
import crawl_site  # noqa: E402
import link_recheck  # noqa: E402
import page_checks  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201"
                    "e5279c1e0000000049454e44ae426082")
PNG_2X = PNG[:-12] + bytes(4) + PNG[-8:]  # a second, different file for the srcset variant


def html(title, body):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title} for the switch test</title>"
            f"<meta name='description' content='A page used to check capture switches.'></head><body><main><h1>{title}</h1>"
            f"<p>{'Words about coffee roasting and brewing at home. ' * 30}</p>{body}</main></body></html>")


PAGES = {
    "/": html("Home", "<img src='/logo.png' alt='Logo'><a href='/a'>A</a> <a href='/b'>B</a> <a href='/app'>App</a> "
                      "<a href='/slow'>Slow</a> <a href='https://external.invalid/x'>Elsewhere</a> Speling mistaek here."),
    "/a": html("Page A", "<a href='/'>Home</a> <a href='/b'>B</a> <a href='/missing'>Missing</a>"),
    "/b": html("Page B", "<img src='/logo.png' srcset='/logo.png 1x, /logo-2x.png 2x' alt='Logo again'><a href='/'>Home</a>"),
    # A single page app shell: --render auto renders this page and no other.
    "/app": ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>App shell for the switch test</title></head>"
             "<body><div id=\"root\"></div><script>document.getElementById('root').innerHTML = '<h1>App</h1><p>' + "
             "'Rendered words about coffee. '.repeat(40) + '</p><a href=\"/\">Home</a>';</script></body></html>"),
    "/slow": html("Slow page", "<a href='/'>Home</a>"),
}


class Site(BaseHTTPRequestHandler):
    slow_sec = 0.0

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/slow" and Site.slow_sec:
            time.sleep(Site.slow_sec)
        if path in PAGES:
            body, kind, code = PAGES[path].encode(), "text/html; charset=utf-8", 200
        elif path in ("/logo.png", "/logo-2x.png"):
            body, kind, code = (PNG if path == "/logo.png" else PNG_2X), "image/png", 200
        elif path == "/robots.txt":
            body, kind, code = b"User-agent: *\nAllow: /\n", "text/plain", 200
        else:
            body, kind, code = b"not found", "text/plain", 404
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def log_message(self, *_args):
        pass


def evidence(manifest: dict, processes: int) -> dict:
    """What the switches changed in this manifest."""
    intel = manifest.get("siteIntel") or {}
    transport = intel.get("transport") or {}
    nodes = manifest.get("nodes") or []
    snapshots = intel.get("snapshots") or {}
    shots = [n.get("snapshot") or {} for n in nodes if n.get("snapshot")]  # each page node carries its own
    return {
        "tasks": "null" if (manifest.get("audit") or {}).get("tasks") is None else "counted",
        "tls": (transport.get("tls") or {}).get("state"),
        "tlsDays": (transport.get("tls") or {}).get("daysRemaining"),
        "dns": (transport.get("emailDns") or {}).get("state"),
        "assets": sum(1 for r in manifest.get("resources") or [] if r.get("localPath")),
        "browser": (intel.get("browserAudit") or {}).get("state"),
        "browserPages": len((intel.get("browserAudit") or {}).get("pages") or []),
        "snapshots": snapshots.get("state"),
        "snapshotCount": sum(1 for s in shots if s.get("screenshot")),
        "snapshotHtml": sum(1 for s in shots if s.get("html")),
        "pages": (manifest.get("pipelineMetrics") or {}).get("pages"),
        "rendered": sorted(n.get("url", "").rsplit("/", 1)[-1] or "/" for n in nodes if n.get("renderUsed")),
        "externalAttempted": (manifest.get("linkHealth") or {}).get("attemptedCount"),
        "spelling": sum(1 for n in nodes if ((n.get("pageChecks") or {}).get("spelling") or {}).get("checkedWords")),
        "deadline": any("deadline" in str(w).lower() for w in manifest.get("captureWarnings") or []),
        "processes": processes,
    }


# The quiet settings other suites use; each case changes one thing from here.
BASE = dict(max_pages=5, render_mode="never", download_images=False, delay_sec=0, check_external=False, parallel=False,
            browser_audit=False, snapshot_limit=0, dns_checks=False, tls_check=False)
# name: (options, needs, expected change). "needs" names what the environment must provide.
CASES = {
    "engine defaults (every check on)": (dict(max_pages=5, delay_sec=0), {"browser"},
        lambda e: e["browser"] == "ok" and e["snapshots"] == "ok" and e["assets"] >= 1 and e["externalAttempted"] and e["processes"] > 0),
    "quiet baseline": ({}, set(),
        lambda e: e["browser"] == "skipped" and e["snapshots"] == "skipped" and e["assets"] == 0 and not e["externalAttempted"]
        and e["processes"] == 0 and e["tls"] == "skipped" and e["rendered"] == [] and e["tasks"] == "counted"),
    "--no-tasks": (dict(tasks=False), set(), lambda e: e["tasks"] == "null"),
    "TLS check on (HTTPS loopback, test CA)": (dict(tls_check=True, _https=True), {"https"},
        lambda e: e["tls"] in ("ok", "warn") and (e["tlsDays"] or 0) > 300),
    "email DNS checks on": (dict(dns_checks=True), {"dns"}, lambda e: e["dns"] not in (None, "skipped")),
    "images saved (preferred)": (dict(download_images=True), set(), lambda e: e["assets"] == 1),
    "images saved (--image-mode all)": (dict(download_images=True, image_mode="all"), set(), lambda e: e["assets"] >= 2),
    "--render auto": (dict(render_mode="auto"), {"browser"}, lambda e: e["rendered"] == ["app"]),
    "--render always": (dict(render_mode="always"), {"browser"}, lambda e: len(e["rendered"]) >= 4),
    "browser audit on (--render auto)": (dict(render_mode="auto", browser_audit=True), {"browser"},
        lambda e: e["browser"] == "ok" and e["browserPages"] >= 1),
    "browser audit on with --render never": (dict(browser_audit=True), set(), lambda e: e["browser"] == "skipped"),
    "snapshots on, limit 2 (--render auto)": (dict(render_mode="auto", snapshot_limit=2), {"browser"},
        lambda e: e["snapshots"] == "ok" and e["snapshotCount"] == 2 and e["snapshotHtml"] == 0),
    "snapshots with --snapshot-html": (dict(render_mode="auto", snapshot_limit=2, snapshot_html=True), {"browser"},
        lambda e: e["snapshots"] == "ok" and e["snapshotHtml"] >= 1),
    "external links checked": (dict(check_external=True), set(), lambda e: (e["externalAttempted"] or 0) >= 1),
    "parallel workers": (dict(parallel=True), set(), lambda e: e["processes"] > 0),
    "--spell-check": (dict(spell_check=True), {"spell"}, lambda e: e["spelling"] >= 1),
    "--max-pages 1": (dict(max_pages=1), set(), lambda e: e["pages"] == 1),
    "--deadline cuts the capture": (dict(deadline_sec=2.0, _slow=4.0), set(), lambda e: e["deadline"]),
}

PARSE = """
import { build } from 'esbuild';
import { readFileSync } from 'node:fs';
const out = await build({ entryPoints: ['src/data/validateManifest.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
const { parseSiteManifest } = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].contents).toString('base64'));
const results = {};
for (const [name, path] of Object.entries(JSON.parse(process.argv[1]))) {
  try { parseSiteManifest(JSON.parse(readFileSync(path, 'utf8'))); results[name] = 'opens'; }
  catch (error) { results[name] = 'refused: ' + error.message; }
}
console.log(JSON.stringify(results));
"""


def app_verdicts(paths: dict) -> dict:
    run = subprocess.run(["node", "--input-type=module", "-e", PARSE, json.dumps(paths)], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        raise RuntimeError(run.stderr[-2000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


def browser_problem():
    """None when the engine's own Chromium lookup finds a browser that starts, else why not."""
    try:
        from playwright.sync_api import sync_playwright
        from browser_runtime import resolve_chromium_executable
        with sync_playwright() as driver:
            resolved = resolve_chromium_executable(driver)
            if not resolved.get("executablePath"):
                return resolved.get("error") or "no compatible Chromium was found"
            driver.chromium.launch(headless=True, executable_path=resolved["executablePath"], timeout=30000).close()
        return None
    except Exception as exc:  # any failure to start is a reason, not a test failure
        return f"Chromium did not start ({type(exc).__name__}: {str(exc).splitlines()[0][:120]})"


def make_test_ca(folder: Path):
    """A throwaway certificate authority and a 127.0.0.1 certificate, valid for 400 days."""
    if not shutil.which("openssl"):
        return None, "openssl is not installed, so no test certificate can be made"
    def run(*args):
        subprocess.run(["openssl", *args], cwd=folder, check=True, capture_output=True, timeout=60)
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "400",
        "-subj", "/CN=Web-Obs switch test CA", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign")
    run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "site.key", "-out", "site.csr", "-subj", "/CN=127.0.0.1")
    (folder / "ext.cnf").write_text("subjectAltName=IP:127.0.0.1\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n")
    run("x509", "-req", "-in", "site.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out", "site.pem",
        "-days", "400", "-extfile", "ext.cnf")
    return folder, None


class ManifestSwitches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        targets = [f"127.0.0.1:{cls.server.server_port}"]
        cls.https_origin, cls.ca = None, None
        certs, problem = make_test_ca(Path(cls.tmp.name))
        if certs:
            cls.https = ThreadingHTTPServer(("127.0.0.1", 0), Site)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certs / "site.pem", certs / "site.key")
            cls.https.socket = context.wrap_socket(cls.https.socket, server_side=True)
            threading.Thread(target=cls.https.serve_forever, daemon=True).start()
            cls.https_origin = f"https://127.0.0.1:{cls.https.server_port}"
            cls.ca = str(certs / "ca.pem")
            targets.append(f"127.0.0.1:{cls.https.server_port}")
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": ",".join(targets), "CLAUDE_SEO_LOCAL_TARGETS": ""})
        cls.env.start()
        try:
            import dns  # noqa: F401
            dns_problem = "a loopback site is addressed by IP, and email DNS checks need a dotted domain name"
        except ImportError:
            dns_problem = "dnspython is not installed, and a loopback site has no dotted domain name"
        cls.unavailable = {
            "browser": browser_problem(),
            "https": problem,
            "dns": dns_problem,
            "spell": None if page_checks.SpellChecker is not None else "pyspellchecker is not installed",
        }

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        for server in (cls.server, getattr(cls, "https", None)):
            if server:
                server.shutdown()
                server.server_close()
        cls.tmp.cleanup()

    def capture(self, name, options):
        options = dict(options)
        Site.slow_sec = options.pop("_slow", 0.0)
        https = options.pop("_https", False)
        settings = dict(BASE) if name != "engine defaults (every check on)" else {}
        settings.update(options)
        vault = Path(self.tmp.name) / f"case{len([p for p in os.listdir(self.tmp.name) if p.startswith('case')])}"
        vault.mkdir()
        starts = []
        real_start = multiprocessing.process.BaseProcess.start

        def counting_start(process):
            starts.append(process.name)
            return real_start(process)
        trust = {"SSL_CERT_FILE": self.ca, "REQUESTS_CA_BUNDLE": self.ca} if https else {}
        try:
            with redirect_stdout(io.StringIO()), patch.object(multiprocessing.process.BaseProcess, "start", counting_start), \
                    patch.dict(os.environ, trust):
                manifest = crawl_site.crawl_website_to_vault(self.https_origin if https else self.origin, str(vault), **settings)
        finally:
            Site.slow_sec = 0.0
        return vault, manifest, len(starts)

    def test_every_switch_takes_effect_and_opens(self):
        paths, shapes, effects, skipped = {}, {}, {}, {}
        for name, (options, needs, expected) in CASES.items():
            reasons = [self.unavailable[need] for need in sorted(needs) if self.unavailable.get(need)]
            if reasons:
                skipped[name] = "; ".join(reasons)
                continue
            vault, manifest, processes = self.capture(name, options)
            ev = evidence(manifest, processes)
            paths[name] = str(vault / "sites" / manifest["siteId"] / "_site-graph.json")
            shapes[name] = ev
            effects[name] = bool(expected(ev))
            if name == "quiet baseline":
                # Keep the capture's own manifest, then recheck links, which rewrites it in place.
                before = Path(self.tmp.name) / "baseline-before-recheck.json"
                before.write_bytes(Path(paths[name]).read_bytes())
                with redirect_stdout(io.StringIO()):
                    link_recheck.continue_link_checks(manifest["siteId"], str(vault), lambda *a, **k: None, max_seconds=10)
                rechecked = json.loads(Path(paths[name]).read_text(encoding="utf-8"))
                attempted = (rechecked.get("linkHealth") or {}).get("attemptedCount") or 0
                paths["--continue-links after a capture"] = paths[name]
                shapes["--continue-links after a capture"] = {"externalAttempted": attempted}
                effects["--continue-links after a capture"] = attempted >= 1
                paths[name] = str(before)
        verdicts = app_verdicts(paths)
        print("", file=sys.stderr)
        for name in paths:
            mark = "took effect" if effects[name] else "NO EFFECT"
            print(f"  {verdicts[name]:<8} {mark:<12} {name}: {json.dumps(shapes[name], separators=(',', ':'))}", file=sys.stderr)
        for name, reason in skipped.items():
            print(f"  not exercisable here: {name}: {reason}", file=sys.stderr)
        exercised = [name for name in paths if effects[name] and verdicts[name] == "opens"]
        print(f"  {len(exercised)} exercised, {len(skipped)} not exercisable", file=sys.stderr)
        self.assertEqual({name: verdict for name, verdict in verdicts.items() if verdict != "opens"}, {})
        self.assertEqual([name for name, ok in effects.items() if not ok], [], "every switch that ran changed its manifest")
        self.assertEqual(len(paths) + len(skipped), len(CASES) + (1 if "quiet baseline" in paths else 0))

    def test_malformed_task_counts_are_still_refused(self):
        vault, manifest, _processes = self.capture("quiet baseline", {})
        site = Path(vault) / "sites" / manifest["siteId"]
        good = json.loads((site / "_site-graph.json").read_text(encoding="utf-8"))
        variants = {"tasks null": None, "tasks counts": {"open": 3, "resolved": 0},
                    "negative count": {"open": -1, "resolved": 0}, "text count": {"open": "3"}, "tasks list": [1, 2]}
        paths = {}
        for label, tasks in variants.items():
            changed = json.loads(json.dumps(good))
            changed["audit"]["tasks"] = tasks
            path = site / f"variant-{len(paths)}.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            paths[label] = str(path)
        verdicts = app_verdicts(paths)
        self.assertEqual(verdicts["tasks null"], "opens")
        self.assertEqual(verdicts["tasks counts"], "opens")
        self.assertIn("invalid task counts", verdicts["negative count"])
        self.assertIn("invalid task counts", verdicts["text count"])
        self.assertIn("invalid audit tasks", verdicts["tasks list"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
