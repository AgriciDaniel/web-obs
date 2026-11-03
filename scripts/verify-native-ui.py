#!/usr/bin/env python3
"""Attach to an explicitly isolated Obsidian test vault through local CDP.

Launch the installed desktop app with a separate profile first. This harness
refuses a different vault, runs local HTTP fixtures, and never closes the app.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--vault', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--expect-no-webgl', action='store_true')
    parser.add_argument('--render-mode', choices=['auto', 'always', 'never'], default='never')
    parser.add_argument('--spa-fixture', action='store_true')
    parser.add_argument('--media-fixture', action='store_true')
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('verify-system.py')
    spec = importlib.util.spec_from_file_location('local_native_fixture', source)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    external = ThreadingHTTPServer(('127.0.0.1', 0), fixture.External)
    class NativeWebsite(fixture.Website):
        def do_HEAD(self):
            if args.spa_fixture and self.path == '/native-app.js':
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript')
                self.end_headers()
                return
            if args.media_fixture and self.path in ('/episode.mp3', '/clip.mp4'):
                self.send_response(200)
                self.send_header('Content-Type', 'audio/mpeg' if self.path.endswith('.mp3') else 'video/mp4')
                self.end_headers()
                return
            self.send_response(404)
            self.end_headers()

        def do_GET(self):
            if args.media_fixture and self.path.startswith('/captions-') and self.path.endswith('.vtt'):
                fixture.Website.hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'text/vtt')
                self.end_headers()
                self.wfile.write(b'WEBVTT\n\n00:00.000 --> 00:01.000\nLocal caption.\n')
                return
            if args.spa_fixture and self.path in ('/', '/native-app.js'):
                fixture.Website.hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html' if self.path == '/' else 'application/javascript')
                self.end_headers()
                if self.path == '/':
                    self.wfile.write(b'<html><head><title>Source business</title></head><body><div id="root"></div><script src="/native-app.js"></script></body></html>')
                else:
                    links = ''.join(f'<a href="http://localhost:{external.server_port}{path}">{path}</a>' for path in ['/ok','/gone','/denied','/server-error'])
                    media = '<audio src="/episode.mp3"></audio><video src="/clip.mp4">' + ''.join(f'<track src="/captions-{i}.vtt" kind="captions" srclang="en">' for i in range(4)) + '</video>' if args.media_fixture else ''
                    html = media + '<h1>Important hero</h1><p>' + 'Rendered local source. ' * 20 + '</p><button aria-controls="answer">Question?</button><div id="answer" hidden>Hidden FAQ answer.</div>' + links
                    self.wfile.write(('document.getElementById("root").innerHTML=' + json.dumps(html) + ';').encode())
                return
            super().do_GET()
    website = ThreadingHTTPServer(('127.0.0.1', 0), NativeWebsite)
    fixture.Website.external_port = external.server_port
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (external, website)]
    for thread in threads:
        thread.start()
    origin = f'http://127.0.0.1:{website.server_port}'
    results = []
    def passed(name):
        results.append({'name': name, 'status': 'PASS', 'evidenceClass': 'Actual isolated Obsidian desktop app through local CDP'})
        print('[PASS]', name, flush=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
            page = next(p for c in browser.contexts for p in c.pages if p.url.startswith('app://obsidian.md/'))
            page.set_viewport_size({'width': 1440, 'height': 1000})
            actual = page.evaluate('app.vault.adapter.getBasePath()')
            if Path(actual).resolve() != args.vault.resolve():
                raise RuntimeError('Refusing to operate on a different vault.')
            passed('Isolated vault identity confirmed')
            allowlist = f'127.0.0.1:{website.server_port},localhost:{external.server_port}'
            page.evaluate("value => { require('process').env.WEB_OBS_LOCAL_TARGETS = value; }", allowlist)
            page.evaluate("async mode => { delete require('process').env.PLAYWRIGHT_BROWSERS_PATH; await app.plugins.disablePlugin('web-obs'); await app.plugins.enablePlugin('web-obs'); const plugin=app.plugins.plugins['web-obs']; plugin.settings.renderMode=mode; plugin.settings.downloadImages=false; await plugin.saveSettings(); app.commands.executeCommandById('web-obs:open-site-globe'); }", args.render_mode)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.get_by_placeholder('websiteexample.com', exact=True).wait_for(timeout=15000)
            if args.expect_no_webgl:
                page.get_by_text('3D view unavailable', exact=True).wait_for()
                passed('Graphics failure leaves capture UI available')
            page.get_by_placeholder('websiteexample.com', exact=True).fill(origin)
            button = page.get_by_role('button', name='Start', exact=True)
            if not button.count():
                button = page.get_by_role('button', name='Capture', exact=True)
            button.click()
            page.locator('.wo-progress-card').wait_for(timeout=10000)
            for label in ('Pages and text', 'Images and attachments', 'Link checks'):
                assert page.get_by_text(label, exact=True).is_visible()
            assert 'Page limit' in page.locator('.wo-progress-limits').inner_text()
            page.wait_for_function("() => document.querySelector('.wo-progress-card')?.textContent.includes('completed')", timeout=20000)
            page.screenshot(path=str(args.evidence / 'native-capture-progress.png'))
            passed('Native capture shows independent page, media and link queues')
            site_id = f'127.0.0.1-{website.server_port}'
            page.get_by_role('combobox', name='Captured websites').locator(f'option[value="{site_id}"]').wait_for(state='attached', timeout=30000)
            page.get_by_role('complementary', name='Page explorer').wait_for()
            manifest_file = args.vault / 'sites' / site_id / '_site-graph.json'
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
            assert manifest['stats']['pagesCrawled'] == 1
            if args.spa_fixture:
                assert next(n for n in manifest['nodes'] if n['kind'] == 'home')['renderUsed']
                passed('Selected render mode produced SPA content through the native Python child')
            assert page.get_by_text('Partial snapshot', exact=True).is_visible()
            expected_targets = 4 + int(args.spa_fixture) + (6 if args.media_fixture else 0)
            assert manifest['linkHealth']['totalCount'] == expected_targets
            assert '/private' not in fixture.Website.hits
            passed('Native UI starts Python, enforces robots and loads saved capture')
            if not args.expect_no_webgl:
                page.locator('.wo-canvas-stage canvas').wait_for()
                assert page.locator('.wo-kind-home .wo-pill-label').inner_text() == manifest['domain']
                passed('Native 3D renderer draws the captured graph with its domain label')
            page.get_by_role('button', name='Site Intel', exact=True).click()
            intel = page.get_by_role('complementary', name='Site Intelligence')
            assert f'{expected_targets} of {expected_targets} observed targets attempted' in intel.inner_text()
            assert '1 returned 404/410' in intel.inner_text()
            passed('Native Site Intel renders actual direct link-check results')
            if args.media_fixture:
                transcripts = [r for r in manifest['resources'] if r['type'] == 'transcript']
                assert len(transcripts) == 4 and all(r.get('localPath') for r in transcripts)
                assert not any(n['path'].endswith('.vtt') for n in manifest['nodes'])
                assert all(r['downloadState'] == 'reference' for r in manifest['resources'] if r['type'] in ('audio', 'video'))
                assert '4 caption or transcript files' in intel.inner_text()
                assert page.get_by_role('button', name='Open media inventory', exact=True).is_visible()
                passed('Native capture saves captions separately and keeps large media as references')
            geometry = page.evaluate("""() => {
              const shell = document.querySelector('.wo-shell');
              const summary = shell.querySelector('.wo-site-overview').getBoundingClientRect();
              const header = shell.querySelector('.wo-topbar').getBoundingClientRect();
              const drawer = shell.querySelector('.wo-intel-drawer').getBoundingClientRect();
              const leaf = shell.getBoundingClientRect();
              return {headerClear: header.bottom <= summary.top, drawerInside: drawer.left >= leaf.left && drawer.right <= leaf.right, leafWidth: leaf.width};
            }""")
            assert geometry['headerClear'] and geometry['drawerInside'], geometry
            passed('Native split-pane layout keeps toolbar, summary and drawer within its leaf')
            page.screenshot(path=str(args.evidence / ('native-no-gl.png' if args.expect_no_webgl else 'native-globe.png')))
            page.keyboard.press('Escape')
            page.get_by_role('complementary', name='Page explorer').locator('.wo-page-row').first.click()
            page.get_by_role('complementary', name='Page Inspector').wait_for()
            if args.media_fixture:
                details = page.get_by_role('complementary', name='Page Inspector').locator('.wo-resource-details')
                details.locator('summary').click()
                assert details.evaluate('(element) => element.open')
                assert details.locator('.wo-link-row').count() == 7
                page.screenshot(path=str(args.evidence / 'native-inspector-media.png'))
                passed('Native inspector expands the page media and resource references')
            page.get_by_role('button', name='Open Note', exact=True).click()
            page.wait_for_function("() => app.workspace.getLeavesOfType('markdown').some(l=>l.view.file?.path?.endsWith('/pages/index.md'))")
            passed('Native inspector opens its captured Markdown note')
            note = args.vault / 'sites' / site_id / 'pages/index.md'
            assert 'Important hero' in note.read_text(encoding='utf-8') and 'Hidden FAQ answer.' in note.read_text(encoding='utf-8')
            page.evaluate("async () => { await app.internalPlugins.plugins.bases.enable(); }")
            page.evaluate("async path => { await app.workspace.openLinkText(path, '', true); }", f'sites/{site_id}/_pages.base')
            page.wait_for_function("() => app.workspace.getLeavesOfType('bases').some(l=>l.view.file?.path?.endsWith('/_pages.base'))", timeout=15000)
            page.wait_for_timeout(500)
            assert 'Failed to load' not in page.locator('body').inner_text()
            assert 'Source business' in page.locator('body').inner_text()
            passed('Generated Bases file opens and shows captured page in Obsidian')
            page.screenshot(path=str(args.evidence / 'native-bases.png'))
            assert not errors, errors
            passed('No uncaught renderer errors during the native capture flow')
    finally:
        for server in (external, website):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(2)
        (args.evidence / 'native-ui-results.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
