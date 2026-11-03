#!/usr/bin/env python3
"""Audit view acceptance against a retained capture; no public scan."""
import argparse
import json
from pathlib import Path
import re
import sys
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from browser_runtime import resolve_chromium_executable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5288')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--cdp')
    parser.add_argument('--vault', type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    errors, results = [], []
    evidence_class = 'Actual isolated Obsidian and installed bundle' if args.cdp else 'Actual Chromium with local mocked transport and retained public capture'

    def passed(name):
        results.append(dict(name=name, status='PASS', evidenceClass=evidence_class))
        print('[PASS]', name, flush=True)

    with sync_playwright() as playwright:
        if args.cdp:
            assert args.vault
            browser = playwright.chromium.connect_over_cdp(args.cdp)
            page = next(p for c in browser.contexts for p in c.pages if p.url.startswith('app://obsidian.md'))
            assert Path(page.evaluate('app.vault.adapter.getBasePath()')) == args.vault.resolve()
            page.reload()
            page.get_by_label('Captured websites', exact=True).select_option(manifest['siteId'])
        else:
            browser = playwright.chromium.launch(headless=True,
                executable_path=resolve_chromium_executable(playwright)['executablePath'],
                args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport=dict(width=1440, height=1050))
            page.route('**/__web_obs/sites', lambda route: route.fulfill(json={'sites': [dict(siteId=manifest['siteId'], domain=manifest['domain'], capturedAt=manifest['capturedAt'], pagesCrawled=manifest['stats']['pagesCrawled'], externalDomains=manifest['stats']['externalDomains'])]}))
            page.route('**/__web_obs/site?*', lambda route: route.fulfill(json=manifest))
            page.goto(args.url)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.get_by_role('button', name='Site audit', exact=True).click()
        audit = page.get_by_role('region', name='Site audit for ' + manifest['domain'], exact=True)
        expect(audit).to_be_visible()
        expect(page.get_by_role('button', name='Close audit', exact=True)).to_be_focused()
        expect(page.locator('.wo-canvas-stage')).to_be_hidden()
        assert not page.get_by_role('complementary', name='Page explorer', exact=True).count()
        passed('Audit opens with keyboard focus and replaces map controls without overlap')

        expect(audit.get_by_role('img', name=re.compile('^Link status distribution:'))).to_be_visible()
        expect(audit.get_by_role('img', name=re.compile('^Resource download states:'))).to_be_visible()
        expect(audit.get_by_role('heading', name='Pages by section', exact=True)).to_be_visible()
        expect(audit.locator('.wo-audit-stats')).to_contain_text(str(manifest['stats']['pagesCrawled']))
        expect(audit.locator('.wo-audit-stats')).to_contain_text(str(manifest['linkHealth']['totalCount']))
        expect(audit).to_contain_text('Not assessed')
        expect(audit).to_contain_text('There is no overall health grade')
        passed('Charts expose actual capture totals and unassessed areas without an invented grade')
        page.screenshot(path=str(args.evidence / 'audit-desktop.png'))

        search = audit.get_by_role('searchbox', name='Search recorded findings and affected URLs', exact=True)
        search.fill('not-a-real-finding-123')
        expect(audit.get_by_role('heading', name='No matching findings', exact=True)).to_be_visible()
        audit.get_by_role('button', name='Clear filters', exact=True).click()
        audit.get_by_role('group', name='Filter findings by category').get_by_role('button', name=re.compile('^Page signals')).click()
        finding = audit.locator('.wo-audit-finding').first
        finding.locator('summary').click()
        finding.get_by_role('button', name='Inspect page', exact=True).first.click()
        expect(page.get_by_role('complementary', name='Page Inspector', exact=True)).to_be_visible()
        expect(audit).to_have_count(0)
        page.get_by_role('button', name='Close inspector', exact=True).click()
        expect(page.get_by_role('button', name='Site audit', exact=True)).to_be_focused()
        passed('Search, category filtering and affected-page inspection use actual captured findings')

        page.get_by_role('button', name='Site audit', exact=True).click()
        page.keyboard.press('Escape')
        expect(audit).to_have_count(0)
        expect(page.get_by_role('button', name='Site audit', exact=True)).to_be_focused()
        page.get_by_role('button', name='Site audit', exact=True).click()
        page.get_by_role('tab', name='Road', exact=True).click()
        expect(audit).to_have_count(0)
        expect(page.locator('.wo-canvas-stage')).to_be_visible()
        passed('Escape restores the launcher and layout tabs return to the map')

        if not args.cdp:
            for width, height in ((1280, 900), (900, 900), (390, 844)):
                page.set_viewport_size(dict(width=width, height=height))
                page.get_by_role('button', name='Site audit', exact=True).click()
                box = audit.bounding_box()
                header = page.locator('.wo-topbar').bounding_box()
                assert box and header and box['y'] >= header['y'] + header['height'] - 2, (width, box, header)
                assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
                assert audit.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                assert audit.locator('.wo-audit-body').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                page.screenshot(path=str(args.evidence / f'audit-{width}.png'))
                page.get_by_role('button', name='Close audit', exact=True).click()
            passed('Charts and controls fit 1280px, 900px and 390px without horizontal clipping or header overlap')
        assert not errors, errors
        passed('No uncaught renderer errors during audit navigation')
        if not args.cdp:
            browser.close()
    (args.evidence / 'results.json').write_text(json.dumps(dict(results=results, errors=errors), indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
