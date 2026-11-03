#!/usr/bin/env python3
"""Browser discovery regressions plus optional real Flatpak Auto rendering."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from browser_runtime import resolve_chromium_executable


class BrowserDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.relative = Path('chromium-1234/chrome-linux64/chrome')
        self.expected = self.home / '.var/app/test/cache/ms-playwright' / self.relative
        if sys.platform == 'darwin':
            self.cache = self.home / 'Library/Caches/ms-playwright'
        elif os.name == 'nt':
            self.cache = self.home / 'AppData/Local/ms-playwright'
        else:
            self.cache = self.home / '.cache/ms-playwright'
        self.host = self.cache / self.relative
        self.driver = SimpleNamespace(chromium=SimpleNamespace(executable_path=str(self.expected)))
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.home_patch = patch('browser_runtime.Path.home', return_value=self.home)
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.environment.stop()
        self.temp.cleanup()

    def binary(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('local executable fixture', encoding='utf-8')
        path.chmod(0o755)

    def test_default_installation_wins(self):
        self.binary(self.expected)
        self.binary(self.host)
        self.assertEqual(resolve_chromium_executable(self.driver)['executablePath'], str(self.expected))

    def test_flatpak_cache_miss_uses_matching_host_revision(self):
        self.binary(self.host)
        result = resolve_chromium_executable(self.driver)
        self.assertEqual(result['executablePath'], str(self.host))
        self.assertEqual(result['source'], 'standard-user-cache')
        self.assertEqual(result['expectedPath'], str(self.expected))

    def test_old_browser_revision_is_not_selected(self):
        self.binary(self.cache / 'chromium-1233/chrome-linux64/chrome')
        self.assertIsNone(resolve_chromium_executable(self.driver)['executablePath'])

    def test_explicit_browser_override_is_not_bypassed(self):
        self.binary(self.host)
        for override in ('/chosen/cache', '0'):
            with patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH': override}):
                result = resolve_chromium_executable(self.driver)
                self.assertIsNone(result['executablePath'])
                self.assertIn('configured PLAYWRIGHT_BROWSERS_PATH', result['error'])

    def test_empty_override_uses_standard_cache(self):
        self.binary(self.host)
        with patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH': ''}):
            self.assertEqual(resolve_chromium_executable(self.driver)['executablePath'], str(self.host))
            self.assertEqual(os.environ['PLAYWRIGHT_BROWSERS_PATH'], '')

    @unittest.skipIf(os.name == 'nt', 'Windows has no executable permission bit')
    def test_nonexecutable_file_is_not_ready(self):
        self.binary(self.host)
        self.host.chmod(0o644)
        self.assertIsNone(resolve_chromium_executable(self.driver)['executablePath'])

    def test_discovery_does_not_mutate_process_environment(self):
        self.binary(self.host)
        before = dict(os.environ)
        resolve_chromium_executable(self.driver)
        self.assertEqual(before, dict(os.environ))


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<html><head><title>Auto render fixture</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>')
        elif self.path == '/app.js':
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.end_headers()
            self.wfile.write(b'document.getElementById("root").innerHTML="<h1>Rendered inside Flatpak</h1><p>Local browser content.</p>";')
        else:
            self.send_response(404)
            self.end_headers()


def verify_flatpak():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from browser_runtime import resolve_chromium_executable
from playwright.sync_api import sync_playwright
from extractor import fetch_page_html
checks = []
for override in (None, ''):
    if override is None:
        os.environ.pop('PLAYWRIGHT_BROWSERS_PATH', None)
    else:
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = override
    with sync_playwright() as p:
        discovery = resolve_chromium_executable(p)
        assert discovery['executablePath'], discovery
    result = fetch_page_html(sys.argv[2], render_mode='auto')
    assert result['error'] is None, result['error']
    assert result['render_used'], 'Auto did not render the SPA fixture'
    assert 'Rendered inside Flatpak' in result['html']
    checks.append({'discovery':discovery,'autoRendered':True,'override':override})
print(json.dumps({'checks':checks,'xdgCacheHome':os.environ.get('XDG_CACHE_HOME')}))
'''
    try:
        python = ROOT / 'engine/.venv/bin/python3'
        command = ['flatpak', 'run', f'--env=WEB_OBS_LOCAL_TARGETS=127.0.0.1:{server.server_port}',
                   '--unset-env=PLAYWRIGHT_BROWSERS_PATH', f'--command={python}',
                   'md.obsidian.Obsidian', '-B', '-c', code, str(ROOT / 'engine'), f'http://127.0.0.1:{server.server_port}/']
        if Path('/.flatpak-info').exists():
            command = ['flatpak-spawn', '--host'] + command
        completed = subprocess.run(command, text=True, capture_output=True, timeout=45)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        print('[PASS] Actual Flatpak Auto rendering with no browser-path override:', completed.stdout.strip())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--flatpak', action='store_true')
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BrowserDiscoveryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.flatpak:
        verify_flatpak()
