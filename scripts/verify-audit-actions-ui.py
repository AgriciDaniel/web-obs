#!/usr/bin/env python3
"""Chromium acceptance for audit controls with a synthetic site and mocked host actions.

No report is uploaded and no capture is moved. File operations and server integration have separate checks.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
HARNESS = """
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import App from '/src/App.tsx';
import {PREVIEW_SITE_MANIFEST} from '/src/data/demoSite.ts';
import '/src/styles/theme.css';
import '/src/styles/ui.css';
import '/src/styles/map.css';
import '/src/styles/audit.css';
const manifest = structuredClone(PREVIEW_SITE_MANIFEST);
manifest.siteId = manifest.domain = 'audit-ui.test';
let archived = false;
window.testCalls = {publish: 0, archive: 0};
const actions = {
  approver: '', publishReady: true, publishTargetLabel: 'audit.example.test',
  publish: async (id, name) => {
    window.testCalls.publish++;
    window.testCalls.approver = name;
    return new Promise(resolve => { window.resolvePublish = () => resolve({
      file: null, folder: null, pushedTo: 'audit.example.test',
      link: 'https://audit.example.test/r/synthetic-token', expires: '2030-01-01T00:00:00Z',
      sizeKb: 12, clientName: 'Synthetic', findings: 3, top: ['Synthetic finding'],
    }); });
  },
  previewArchive: async () => ({domain: manifest.siteId, files: 3, bytes: 100,
    items: [{label: 'capture', rel: 'sites/audit-ui.test', files: 3, bytes: 100}]}),
  archive: async (id, confirm) => {
    if (confirm !== id) throw new Error('Confirmation required');
    window.testCalls.archive++;
    archived = true;
    return {domain: id, files: 3, trash: '.web-obs/trash/audit-ui.test-synthetic'};
  },
};
const host = {
  mode: 'obsidian', vaultName: 'Synthetic', auditActions: actions,
  listSites: async () => archived ? [] : [{siteId: manifest.siteId, domain: manifest.domain, pagesCrawled: manifest.stats.pagesCrawled}],
  loadSiteManifest: async () => archived ? null : manifest,
  startCrawl: async () => {}, cancelCrawl: () => {},
  onOpenNote: () => {}, onOpenExternalUrl: () => {},
};
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App, {host}));
"""


def main():
    evidence = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='wo-audit-ui-'))
    evidence.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    server = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors = []
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url, timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError('Local Vite server did not start')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: print('Browser console:', message.text, flush=True) if message.type == 'error' else None)
            page.route('**/src/main.tsx', lambda route: route.fulfill(content_type='application/javascript', body=HARNESS))
            page.goto(url)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(evidence / 'initial.png'))
            assert not errors, errors
            page.get_by_role('button', name='Site audit', exact=True).click()
            page.get_by_role('button', name='Publish audit', exact=True).click()
            dialog = page.get_by_role('dialog', name='Publish audit', exact=True)
            approve = dialog.get_by_role('button', name='Approve and create report')
            expect(approve).to_be_disabled()
            dialog.get_by_role('textbox', name='Approved by').fill('Synthetic Approver')
            expect(approve).to_be_enabled()
            approve.click()
            expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_disabled()
            expect(page.get_by_role('button', name='Archive audit', exact=True)).to_be_disabled()
            page.evaluate('window.resolvePublish()')
            expect(dialog.get_by_text('Client report published', exact=True)).to_be_visible()
            expect(dialog.get_by_role('link')).to_have_attribute('href', 'https://audit.example.test/r/synthetic-token')
            page.screenshot(path=str(evidence / 'published-desktop.png'))
            dialog.get_by_role('button', name='Close', exact=True).click()
            page.get_by_role('button', name='Archive audit', exact=True).click()
            archive = page.get_by_role('alertdialog', name='Archive audit', exact=True)
            move = archive.get_by_role('button', name='Move to the trash folder', exact=True)
            expect(move).to_be_disabled()
            confirm = archive.get_by_role('textbox', name='Type the site name to confirm')
            confirm.fill('wrong.test')
            expect(move).to_be_disabled()
            confirm.fill('audit-ui.test')
            expect(move).to_be_enabled()
            page.screenshot(path=str(evidence / 'archive-desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(move).to_be_visible()
            box = archive.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= 391, box
            page.screenshot(path=str(evidence / 'archive-narrow.png'))
            page.set_viewport_size({'width': 320, 'height': 620})
            confirm.scroll_into_view_if_needed()
            expect(confirm).to_be_visible()
            move.scroll_into_view_if_needed()
            move_box = move.bounding_box()
            assert move_box['y'] >= 0 and move_box['y'] + move_box['height'] <= 620, move_box
            page.screenshot(path=str(evidence / 'archive-short-pane.png'))
            move.click()
            expect(page.get_by_role('region', name='Site audit for audit-ui.test', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Archive audit', exact=True)).to_have_count(0)
            calls = page.evaluate('window.testCalls')
            assert calls == {'publish': 1, 'archive': 1, 'approver': 'Synthetic Approver'}, calls
            assert not errors, errors
            browser.close()
        (evidence / 'result.json').write_text(json.dumps({'status': 'PASS', 'evidenceClass': 'Chromium with synthetic site and mocked host actions', 'calls': calls, 'pageErrors': errors}, indent=2) + '\n')
        print(f'[PASS] Audit actions UI: approval, pending controls, publish result, typed archive confirmation, narrow layout and clearing the archived site. Evidence: {evidence}')
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    main()
