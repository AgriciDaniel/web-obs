#!/usr/bin/env python3
"""Exercise settings search and persisted controls in an explicitly disposable native vault."""
import argparse
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    vault = args.vault.resolve()
    assert 'native-review-' in str(vault) and vault.name == 'vault', 'Disposable vaults only'
    args.evidence.mkdir(parents=True, exist_ok=False)
    data = vault / '.obsidian/plugins/web-obs/data.json'
    before = data.read_bytes()
    original = json.loads(before)['downloadImages']
    checks = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
        page = next(p for p in browser.contexts[0].pages if p.url.startswith('app://'))
        assert Path(page.evaluate('app.vault.adapter.basePath')).resolve() == vault
        page.evaluate("() => { app.setting.open();app.setting.openTabById('web-obs'); }")
        page.wait_for_timeout(400)
        settings = next(p for p in browser.contexts[0].pages if p.title().startswith('Settings'))
        errors = []
        settings.on('pageerror', lambda error: errors.append(str(error)))
        search = settings.get_by_placeholder('Search settings...', exact=True)
        search.fill('publish')
        expect(settings.get_by_text('Web-Obs capture, map and client reports', exact=True)).to_be_visible()
        expect(settings.get_by_text('Python executable', exact=True)).to_be_visible()
        checks.append('Modern settings search discovers and renders the Web-Obs settings')
        row = settings.locator('.setting-item').filter(has=settings.get_by_text('Download images locally', exact=True))
        toggle = row.locator('.checkbox-container')
        toggle.click()
        for _ in range(50):
            if json.loads(data.read_text())['downloadImages'] != original:
                break
            page.wait_for_timeout(100)
        assert json.loads(data.read_text())['downloadImages'] != original
        checks.append('A real toggle in the search result persists through the plugin settings API')
        toggle.click()
        for _ in range(50):
            if data.read_bytes() == before:
                break
            page.wait_for_timeout(100)
        assert data.read_bytes() == before, 'Synthetic settings restored byte for byte'
        checks.append('The toggle restores the exact settings preimage')
        assert settings.locator('input[type=password]').count() == 3
        assert all(settings.locator('input[type=password]').nth(i).input_value() == '' for i in range(3))
        checks.append('All three secret inputs stay empty in the search result')
        settings.screenshot(path=str(args.evidence / 'settings-search.png'))
        assert not errors, errors
        page.evaluate('() => { app.setting.close(); }')
        browser.close()
    (args.evidence / 'results.json').write_text(json.dumps({
        'status': 'PASS', 'checks': checks, 'pageErrors': errors,
        'settingsSha256': hashlib.sha256(before).hexdigest(),
    }, indent=2) + '\n')
    for check in checks:
        print('[PASS]', check)


if __name__ == '__main__':
    main()
