#!/usr/bin/env python3
"""Local browser acceptance for map discovery; no crawl or external requests."""
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
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    results, errors = [], []

    def passed(name):
        results.append({'name': name, 'status': 'PASS', 'evidenceClass': 'Actual Chromium browser with the bundled offline sample'})
        print('[PASS]', name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            executable_path=resolve_chromium_executable(playwright)['executablePath'],
            args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        context = browser.new_context(viewport={'width': 1440, 'height': 960}, device_scale_factor=1)
        context.route('**/__web_obs/sites', lambda route: route.fulfill(json={'sites': []}))
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def sample():
            page.goto(args.url)
            page.get_by_text('Or inspect sample 3D Site Globe preview', exact=True).click()
            page.locator('.wo-discovery-start').wait_for(state='attached')

        sample()
        page.screenshot(path=str(args.evidence / 'launcher.png'))
        page.get_by_role('button', name='Explore map highlights', exact=True).click()
        card = page.get_by_role('region', name='Map discovery', exact=True)
        card.wait_for()
        assert page.locator('.wo-discovery-title').inner_text() == 'studio.example'
        assert not page.get_by_role('complementary', name='Page Inspector').count()
        assert page.evaluate('document.activeElement.getAttribute("aria-label")') == 'Close map discovery'
        passed('Explore opens the home highlight with keyboard focus and leaves the map unobstructed')

        page.get_by_role('button', name='Next highlight', exact=True).click()
        next_title = page.locator('.wo-discovery-title').inner_text()
        assert next_title != 'studio.example'
        page.keyboard.press('ArrowLeft')
        assert page.locator('.wo-discovery-title').inner_text() == 'studio.example'
        passed('Manual next and arrow-key previous navigate captured highlights')

        connection = card.locator('.wo-discovery-peer').first
        peer_title = connection.locator('span').inner_text()
        connection.click()
        assert page.locator('.wo-discovery-title').inner_text() == peer_title
        passed('Connection chips move to the referenced captured page')

        picks = []
        for _ in range(4):
            card.get_by_role('button', name='Surprise me with another stop', exact=True).click()
            picks.append(page.locator('.wo-discovery-title').inner_text())
        assert len(set(picks)) == 4, picks
        passed('Surprise prefers four distinct unvisited destinations')

        card.get_by_role('button', name='Inspect this page', exact=True).click()
        page.get_by_role('complementary', name='Page Inspector').wait_for()
        page.get_by_role('button', name='Close inspector', exact=True).click()
        card.wait_for(state='visible')
        passed('Inspect uses the existing drawer and returns to discovery')

        card.get_by_role('button', name='Close map discovery', exact=True).focus()
        page.keyboard.press('Escape')
        assert not card.count()
        expect(page.get_by_role('button', name='Explore map highlights', exact=True)).to_be_focused(timeout=1000)
        passed('Escape closes discovery and restores focus to its launcher')

        page.get_by_role('button', name='Explore map highlights', exact=True).click()
        explorer = page.get_by_role('complementary', name='Page explorer', exact=True)
        explorer.get_by_role('button', name=re.compile('^Flagged')).click()
        page.get_by_role('button', name='Explore map highlights', exact=True).wait_for()
        assert not card.count()
        page.get_by_role('button', name='Explore map highlights', exact=True).click()
        assert 'studio.example' != page.locator('.wo-discovery-title').inner_text()
        page.get_by_role('textbox', name='Search captured pages', exact=True).fill('no-such-captured-place-12345')
        page.get_by_role('button', name='Explore map highlights', exact=True).wait_for(state='detached')
        passed('Filter changes reset discovery and an empty result offers no invented destination')

        sample()
        page.get_by_role('button', name='Explore map highlights', exact=True).click()
        for mode in ('Road', 'Clusters', 'Globe'):
            page.get_by_role('tab', name=mode, exact=True).click()
            card.get_by_role('button', name='Next highlight', exact=True).click()
            assert page.locator('.wo-discovery-title').inner_text()
        passed('Discovery remains usable in Globe, Road and Clusters layouts')
        page.wait_for_timeout(500)
        page.screenshot(path=str(args.evidence / 'discovery-desktop.png'))

        for width, height in ((1280, 800), (900, 700), (390, 844)):
            page.set_viewport_size({'width': width, 'height': height})
            sample()
            page.get_by_role('button', name='Close page explorer', exact=True).click()
            page.get_by_role('button', name='Explore map highlights', exact=True).click()
            page.wait_for_timeout(300)
            box = card.bounding_box()
            stage = page.locator('.wo-canvas-stage').bounding_box()
            assert box and stage
            assert box['x'] >= stage['x'] - 1 and box['x'] + box['width'] <= stage['x'] + stage['width'] + 1
            assert box['y'] >= stage['y'] - 1 and box['y'] + box['height'] <= stage['y'] + stage['height'] + 1
            dock = page.locator('.wo-bottom-dock').bounding_box()
            assert dock and box['y'] + box['height'] <= dock['y'], 'Discovery overlaps the filter dock'
            card.get_by_role('button', name='Next highlight', exact=True).click()
            card.get_by_role('button', name='Inspect this page', exact=True).click()
            page.get_by_role('button', name='Close inspector', exact=True).click()
            card.wait_for(state='visible')
            page.screenshot(path=str(args.evidence / ('discovery-' + str(width) + '.png')))
        passed('Discovery and explicit inspection fit desktop, narrow panes and a 390px viewport')

        page.set_viewport_size({'width': 1440, 'height': 960})
        page.emulate_media(reduced_motion='reduce')
        sample()
        page.get_by_role('button', name='Explore map highlights', exact=True).click()
        assert page.locator('.wo-discovery-start').count() == 0
        transition = card.locator('.wo-discovery-pagination > span').first.evaluate('element => getComputedStyle(element).transitionDuration')
        assert transition == '0s', transition
        transforms = page.evaluate('''async () => {
            const values=[];
            for(let i=0;i<4;i++) {
                await new Promise(resolve=>requestAnimationFrame(resolve));
                values.push(document.querySelector('.wo-node-pill[aria-pressed="true"]')?.style.transform || '');
            }
            return values;
        }''')
        assert transforms[-1] == transforms[-2], transforms
        passed('Reduced motion removes control transitions and discovery camera motion settles immediately')

        page.emulate_media(reduced_motion='no-preference')
        sample()
        home = page.locator('.wo-node-pill').filter(has_text='studio.example').first
        home.click()
        page.get_by_role('complementary', name='Page Inspector').wait_for()
        page.get_by_role('button', name='Close inspector', exact=True).click()
        home.hover()
        page.wait_for_timeout(100)
        assert page.locator('.wo-css2d-layer.is-hovering-node').count() == 1
        passed('Normal node selection and the approved hover-neighborhood behavior still work')
        assert not errors, errors
        passed('No uncaught browser errors during the interaction checks')
        browser.close()
    (args.evidence / 'ui-results.json').write_text(json.dumps({'checks': results, 'errors': errors}, indent=2) + '\n', encoding='utf-8')
    print(str(len(results)) + ' map discovery UI checks passed.')


if __name__ == '__main__':
    main()
