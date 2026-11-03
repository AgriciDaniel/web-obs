#!/usr/bin/env python3
"""Actual Obsidian link continuation against loopback fixtures in an isolated vault."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cdp', default='http://127.0.0.1:39615')
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('continuation_fixture', Path(__file__).with_name('verify-link-continuation.py'))
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    fixture.LinkContinuationTests.setUpClass()
    results = []

    def passed(name):
        results.append(dict(name=name, status='PASS', evidenceClass='Actual isolated Obsidian, real Python 3.14+ child and local HTTP'))
        print('[PASS]', name, flush=True)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(args.cdp)
            page = next(p for c in browser.contexts for p in c.pages if p.url.startswith('app://obsidian.md'))
            assert Path(page.evaluate('app.vault.adapter.getBasePath()')) == args.vault.resolve()
            fixture.Website.page_count = 2
            fixture.Website.version = 1
            capture = fixture.LinkContinuationTests().capture(str(args.vault))
            site = args.vault / 'sites' / capture['siteId']
            baseline = {name: digest for name, digest in fixture.digest_files(site).items() if name.startswith(('pages/', 'assets/')) or name.endswith('.html')}
            page.reload()
            page.wait_for_function('app?.plugins?.plugins?.["web-obs"]')
            page.evaluate('value => { require("process").env.WEB_OBS_LOCAL_TARGETS = value; }', os.environ['WEB_OBS_LOCAL_TARGETS'])
            page.get_by_label('Captured websites', exact=True).select_option(capture['siteId'])
            page.get_by_role('button', name='Site Intel', exact=True).click()
            drawer = page.get_by_role('complementary', name='Site Intelligence')
            expect(drawer).to_contain_text('Python ' + capture['captureProvenance']['runtime']['pythonVersion'])
            expect(drawer).to_contain_text('Observed in 2 of 2 captured HTML pages')
            passed('Native Site Intel displays actual Python 3.14 and observed sample coverage')
            fixture.Requests.clear()
            drawer.get_by_role('button', name='Check remaining', exact=False).click()
            page.wait_for_function('() => !document.querySelector(".wo-progress-card") && document.querySelector(".wo-intel-drawer")?.textContent.includes("Page capture time is unchanged")', timeout=45000)
            after = json.loads((site / '_site-graph.json').read_text(encoding='utf-8'))
            assert after['capturedAt'] == capture['capturedAt']
            assert after['linkHealth']['uncheckedCount'] == 0
            assert tuple(map(int, after['linkCheckSessions'][-1]['provenance']['runtime']['pythonVersion'].split('.')[:2])) >= (3, 14)
            assert not drawer.get_by_role('button', name='Check remaining', exact=False).count()
            passed('Native remaining-target button completes through the real Python child and refreshes the drawer')
            requests = fixture.Requests.snapshot()
            assert requests and any(r['method'] == 'HEAD' for r in requests)
            assert all(r['method'] == 'HEAD' or r['path'] == '/robots.txt' or r['path'] == '/b-gone' and r['range'] == 'bytes=0-1024' for r in requests), requests
            assert baseline == {name: fixture.digest_files(site)[name] for name in baseline}
            passed('Actual continuation uses HEAD with missing-response GET confirmation and preserves captured content')
            assert after['linkHealth']['unknownCount'] > 0
            expect(drawer).to_contain_text('inconclusive')
            page.screenshot(path=str(args.evidence / 'native-continuation.png'))
            passed('Inconclusive destinations remain distinct from confirmed broken links')
            (args.evidence / 'results.json').write_text(json.dumps(dict(results=results, requests=requests), indent=2) + '\n', encoding='utf-8')
    finally:
        fixture.LinkContinuationTests.tearDownClass()


if __name__ == '__main__':
    main()
