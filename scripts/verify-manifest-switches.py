"""Every capture switch produces a manifest the app can open.

Each case runs a loopback capture with one switch changed, then passes the saved _site-graph.json
through the app's own parseSiteManifest (src/data/validateManifest.ts, bundled with esbuild), the
same check the Obsidian plugin and the standalone app run before showing a capture. A link
recheck of a saved capture is checked the same way. Offline: the fixture is on 127.0.0.1.
"""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
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

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201"
                    "e5279c1e0000000049454e44ae426082")


def html(title, body):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title} for the switch test</title>"
            f"<meta name='description' content='A page used to check capture switches.'></head><body><main><h1>{title}</h1>"
            f"<p>{'Words about coffee roasting and brewing at home. ' * 30}</p>{body}</main></body></html>")


PAGES = {
    "/": html("Home", "<img src='/logo.png' alt='Logo'><a href='/a'>A</a> <a href='/b'>B</a> <a href='/slow'>Slow</a> "
                      "<a href='https://external.invalid/x'>Elsewhere</a>"),
    "/a": html("Page A", "<a href='/'>Home</a> <a href='/b'>B</a> <a href='/missing'>Missing</a>"),
    "/b": html("Page B", "<img src='/logo.png' srcset='/logo.png 1x, /logo.png 2x' alt='Logo again'><a href='/'>Home</a>"),
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
        elif path == "/logo.png":
            body, kind, code = PNG, "image/png", 200
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
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


# The quiet settings other suites use; each case changes one thing from here.
BASE = dict(max_pages=4, render_mode="never", download_images=False, delay_sec=0, check_external=False, parallel=False,
            browser_audit=False, snapshot_limit=0, dns_checks=False, tls_check=False)
CASES = {
    "engine defaults (every check on)": dict(max_pages=4, delay_sec=0),
    "quiet baseline": {},
    "--no-tasks": dict(tasks=False),
    "TLS check on": dict(tls_check=True),
    "email DNS checks on": dict(dns_checks=True),
    "images saved (preferred)": dict(download_images=True),
    "images saved (--image-mode all)": dict(download_images=True, image_mode="all"),
    "--render auto": dict(render_mode="auto"),
    "--render always": dict(render_mode="always"),
    # --render never also turns the browser off, so the browser cases use auto.
    "browser audit on (--render auto)": dict(render_mode="auto", browser_audit=True),
    "browser audit on with --render never": dict(browser_audit=True),
    "snapshots on, limit 2 (--render auto)": dict(render_mode="auto", snapshot_limit=2),
    "snapshots with --snapshot-html": dict(render_mode="auto", snapshot_limit=2, snapshot_html=True),
    "external links checked": dict(check_external=True),
    "parallel workers": dict(parallel=True),
    "--spell-check": dict(spell_check=True),
    "--max-pages 1": dict(max_pages=1),
    "--deadline cuts the capture": dict(deadline_sec=2.0, _slow=4.0),
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


def evidence(manifest: dict) -> str:
    """What each switch changed in this manifest, so a pass shows the switch really took effect."""
    intel = manifest.get("siteIntel") or {}
    transport = intel.get("transport") or {}
    tasks = (manifest.get("audit") or {}).get("tasks")
    deadline = any("deadline" in str(w).lower() or "time limit" in str(w).lower() for w in manifest.get("captureWarnings") or [])
    bits = [f"tasks {'null' if tasks is None else 'counted'}",
            f"tls {(transport.get('tls') or {}).get('state')}",
            f"dns {(transport.get('emailDns') or {}).get('state')}",
            f"saved assets {sum(1 for r in manifest.get('resources') or [] if r.get('localPath'))}",
            f"browser {(intel.get('browserAudit') or {}).get('state')}",
            f"snapshots {(intel.get('snapshots') or {}).get('state')}",
            f"pages {sum(1 for n in manifest.get('nodes') or [] if 'renderUsed' in n)}",
            f"rendered {sum(1 for n in manifest.get('nodes') or [] if n.get('renderUsed'))}"]
    if deadline:
        bits.append("deadline hit")
    return ", ".join(bits)


def app_verdicts(paths: dict) -> dict:
    run = subprocess.run(["node", "--input-type=module", "-e", PARSE, json.dumps(paths)], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        raise RuntimeError(run.stderr[-2000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


class ManifestSwitches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.env = patch.dict(os.environ, {"WEB_OBS_LOCAL_TARGETS": f"127.0.0.1:{cls.server.server_port}", "CLAUDE_SEO_LOCAL_TARGETS": ""})
        cls.env.start()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def capture(self, name, options):
        options = dict(options)
        Site.slow_sec = options.pop("_slow", 0.0)
        settings = dict(BASE) if name != "engine defaults (every check on)" else {}
        settings.update(options)
        vault = Path(self.tmp.name) / f"case{len(os.listdir(self.tmp.name))}"
        vault.mkdir()
        try:
            with redirect_stdout(io.StringIO()):
                manifest = crawl_site.crawl_website_to_vault(self.origin, str(vault), **settings)
        finally:
            Site.slow_sec = 0.0
        return vault, manifest

    def test_every_switch_gives_a_manifest_the_app_opens(self):
        paths, shapes = {}, {}
        for name, options in CASES.items():
            vault, manifest = self.capture(name, options)
            paths[name] = str(vault / "sites" / manifest["siteId"] / "_site-graph.json")
            shapes[name] = evidence(manifest)
            if name == "quiet baseline":
                # Keep the capture's own manifest, then recheck links, which rewrites it in place.
                before = Path(self.tmp.name) / "baseline-before-recheck.json"
                before.write_bytes(Path(paths[name]).read_bytes())
                with redirect_stdout(io.StringIO()):
                    link_recheck.continue_link_checks(manifest["siteId"], str(vault), lambda *a, **k: None, max_seconds=10)
                paths["--continue-links after a capture"] = paths[name]
                shapes["--continue-links after a capture"] = "rechecked in place"
                paths[name] = str(before)
        verdicts = app_verdicts(paths)
        print("", file=sys.stderr)
        for name in paths:
            print(f"  {verdicts[name]:<58} {name} ({shapes[name]})", file=sys.stderr)
        refused = {name: verdict for name, verdict in verdicts.items() if verdict != "opens"}
        self.assertEqual(refused, {})
        self.assertEqual(len(verdicts), len(CASES) + 1)

    def test_malformed_task_counts_are_still_refused(self):
        _vault, manifest = self.capture("quiet baseline", {})
        site = Path(_vault) / "sites" / manifest["siteId"]
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
