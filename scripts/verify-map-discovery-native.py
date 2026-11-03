#!/usr/bin/env python3
"""Read-only discovery acceptance in a separately prepared Obsidian test vault."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cdp', default='http://127.0.0.1:39615')
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--vault', type=Path, required=True)
    args = parser.parse_args()
    results, errors = [], []
    args.evidence.mkdir(parents=True, exist_ok=True)

    def passed(name):
        results.append({'name': name, 'status': 'PASS', 'evidenceClass': 'Actual isolated Obsidian with software WebGL and a copied retained capture'})
        print('[PASS]', name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        page = next(page for context in browser.contexts for page in context.pages if page.url.startswith('app://obsidian.md'))
        page.wait_for_function('window.app?.vault')
        assert Path(page.evaluate('app.vault.adapter.getBasePath()')) == args.vault.resolve(), 'Refusing to act in an unexpected vault'
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.reload()
        page.get_by_label('Captured websites', exact=True).select_option('agricidaniel.com')
        expect(page.locator('.wo-summary-stat').first).to_contain_text('50')
        page.get_by_role('button', name='Explore map highlights', exact=True).click()
        card = page.get_by_role('region', name='Map discovery', exact=True)
        expect(card).to_be_visible()
        assert page.locator('.wo-discovery-title').inner_text() == 'agricidaniel.com'
        assert not page.get_by_role('complementary', name='Page Inspector').count()
        expect(card.get_by_role('button', name='Close map discovery', exact=True)).to_be_focused()
        passed('Packaged discovery opens the retained 50-page capture without opening the inspector')

        home_path = card.locator('.wo-discovery-path').inner_text()
        card.get_by_role('button', name='Next highlight', exact=True).click()
        assert card.locator('.wo-discovery-path').inner_text() != home_path
        page.keyboard.press('ArrowLeft')
        assert card.locator('.wo-discovery-path').inner_text() == home_path
        passed('Native next and arrow-key previous navigate the highlights')

        peer = card.locator('.wo-discovery-peer').first
        expected = peer.locator('span').inner_text()
        peer.click()
        assert card.locator('.wo-discovery-title').inner_text() == expected
        passed('Native connection chips follow captured page relationships')

        paths = []
        for _ in range(3):
            card.get_by_role('button', name='Surprise me with another stop', exact=True).click()
            paths.append(card.locator('.wo-discovery-path').inner_text())
        assert len(set(paths)) == 3
        passed('Native Surprise chooses distinct unvisited pages')

        for mode in ('Road', 'Clusters', 'Globe'):
            page.get_by_role('tab', name=mode, exact=True).click()
            card.get_by_role('button', name='Next highlight', exact=True).click()
            expect(card).to_be_visible()
        box, stage, dock = (page.locator(selector).bounding_box() for selector in ('.wo-discovery-card', '.wo-canvas-stage', '.wo-bottom-dock'))
        assert box and stage and dock
        assert box['x'] >= stage['x'] - 1 and box['x'] + box['width'] <= stage['x'] + stage['width'] + 1
        assert box['y'] >= stage['y'] - 1 and box['y'] + box['height'] <= dock['y']
        assert card.get_by_role('button', name='Inspect this page', exact=True).bounding_box()['height'] >= 30
        assert card.get_by_role('button', name='Next highlight', exact=True).locator('svg').bounding_box()['width'] >= 15
        passed('All native layouts work and the compact card fits above the filter dock')
        page.screenshot(path=str(args.evidence / 'native-discovery.png'))

        card.get_by_role('button', name='Inspect this page', exact=True).click()
        page.get_by_role('complementary', name='Page Inspector').wait_for()
        page.get_by_role('button', name='Close inspector', exact=True).click()
        expect(card).to_be_visible()
        passed('Explicit inspection opens the native drawer and returns to discovery')

        card.get_by_role('button', name='Close map discovery', exact=True).focus()
        page.keyboard.press('Escape')
        expect(page.get_by_role('button', name='Explore map highlights', exact=True)).to_be_focused()
        assert not card.count()
        passed('Native Escape closes the card and restores launcher focus')
        assert not errors, errors
        passed('No uncaught native page errors during the checks')
    (args.evidence / 'native-results.json').write_text(json.dumps({'checks': results, 'errors': errors}, indent=2) + '\n', encoding='utf-8')
    print(str(len(results)) + ' native discovery checks passed.')


if __name__ == '__main__':
    main()
