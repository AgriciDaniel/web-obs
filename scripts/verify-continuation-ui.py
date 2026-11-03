#!/usr/bin/env python3
"""Real Chromium UI acceptance with an explicitly mocked continuation transport."""
import argparse
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from browser_runtime import resolve_chromium_executable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5288')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'sites/agricidaniel.com/_site-graph.json').read_text())
    # Seed an explicit mocked remaining-work case even when the saved live test is exhausted.
    for row in [r for r in manifest['linkHealth']['results'] if r['status'] == 'ok'][:2]:
        row.update(status='unchecked', statusCode=None, attempted=False, method=None, reason='Mocked UI continuation target')
    manifest['linkHealth']['uncheckedCount'] = sum(r['status'] == 'unchecked' for r in manifest['linkHealth']['results'])
    manifest['linkHealth']['checkedCount'] = manifest['linkHealth']['totalCount'] - manifest['linkHealth']['uncheckedCount']
    original_time = manifest['capturedAt']
    manifest['siteIntel']['techStack']['coverage'] = dict(sampledPages=8, capturedHtmlPages=50,
        sourceUrls=[n['url'] for n in manifest['nodes'] if n['kind'] != 'external-domain'][:8],
        selection='Homepage first, then URL order; at most eight HTML pages', securityHeadersScope='Homepage response only')
    results, errors, pending = [], [], []

    def passed(name):
        results.append(dict(name=name, status='PASS', evidenceClass='Actual Chromium; mocked local transport, copied retained capture'))
        print('[PASS]', name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            executable_path=resolve_chromium_executable(playwright)['executablePath'],
            args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport=dict(width=1440, height=960))
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/__web_obs/sites', lambda route: route.fulfill(json={'sites': [dict(siteId=manifest['siteId'], domain=manifest['domain'], capturedAt=manifest['capturedAt'], pagesCrawled=50, externalDomains=29)]}))
        page.route('**/__web_obs/site?*', lambda route: route.fulfill(json=manifest))
        page.route('**/__web_obs/continue-links', lambda route: pending.append(route))
        page.goto(args.url)
        page.get_by_role('button', name='Site Intel', exact=True).click()
        drawer = page.get_by_role('complementary', name='Site Intelligence', exact=True)
        expect(drawer).to_contain_text('Observed in 8 of 50 captured HTML pages')
        expect(drawer).to_contain_text('Security headers: Homepage response only')
        page.screenshot(path=str(args.evidence / 'continuation-intel-desktop.png'))
        passed('Site Intel exposes sample denominator, header scope and remaining-target action')

        drawer.get_by_role('button', name='Check remaining', exact=False).click()
        page.wait_for_function('document.querySelector(".wo-progress-card") !== null')
        assert pending and pending[-1].request.post_data_json['continueLinksSiteId'] == manifest['siteId']
        expect(page.locator('.wo-progress-card')).to_contain_text('CHECKING SAVED TARGETS')
        expect(page.locator('.wo-progress-card')).to_contain_text('Pages and media are kept')
        assert 'Images and attachments' not in page.locator('.wo-progress-card').inner_text()
        page.screenshot(path=str(args.evidence / 'continuation-progress.png'))
        passed('Continuation uses the saved site ID and displays link-only work')
        manifest['linkHealth']['updatedAt'] = '2026-11-02T14:00:00Z'
        manifest['linkHealth']['uncheckedCount'] = 0
        manifest['linkHealth']['checkedCount'] = manifest['linkHealth']['totalCount']
        for row in manifest['linkHealth']['results']:
            if row['status'] == 'unchecked':
                row.update(status='ok', statusCode=200, attempted=True, method='HEAD', reason='Mocked completed UI target')
            if row['status'] == 'broken': row['method'] = 'GET'
        pending.pop().fulfill(content_type='application/x-ndjson', body=json.dumps(dict(event='complete', siteId=manifest['siteId'], captureStatus='complete')) + '\n')
        expect(drawer).to_be_visible()
        expect(drawer).to_contain_text('Page capture time is unchanged')
        assert not drawer.get_by_role('button', name='Check remaining', exact=False).count()
        assert manifest['capturedAt'] == original_time
        passed('Completion refreshes the inspector and removes an exhausted remaining-target action')

        manifest['linkHealth']['uncheckedCount'] = 2
        page.reload()
        page.get_by_role('button', name='Site Intel', exact=True).click()
        drawer.get_by_role('button', name='Check remaining', exact=False).click()
        page.get_by_role('button', name='Cancel', exact=True).click()
        expect(page.locator('.wo-progress-card')).to_have_count(0)
        try:
            pending.pop().abort()
        except Exception:
            pass
        expect(page.locator('.wo-canvas-stage')).to_be_visible()
        passed('Cancel exits link continuation and preserves access to the saved graph')

        page.reload()
        page.get_by_role('button', name='Site Intel', exact=True).click()
        drawer.get_by_role('button', name='Check remaining', exact=False).click()
        pending.pop().fulfill(status=500, body='local fixture failure')
        expect(page.get_by_text('Capture endpoint unavailable (HTTP 500).', exact=True)).to_be_visible()
        expect(drawer).to_be_visible()
        passed('Transport failure is visible while the saved graph remains available')

        page.set_viewport_size(dict(width=390, height=844))
        drawer.get_by_role('button', name='Check remaining', exact=False).scroll_into_view_if_needed()
        button = drawer.get_by_role('button', name='Check remaining', exact=False).bounding_box()
        assert button and button['x'] >= 0 and button['x'] + button['width'] <= 391
        page.screenshot(path=str(args.evidence / 'continuation-intel-390.png'))
        passed('Remaining-target controls fit a 390px viewport')
        assert not errors, errors
        passed('No uncaught browser errors during success, cancellation and failure flows')
        browser.close()
    (args.evidence / 'results.json').write_text(json.dumps(dict(results=results, errors=errors), indent=2) + '\n')


if __name__ == '__main__':
    main()
