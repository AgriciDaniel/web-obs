#!/usr/bin/env python3
"""Verify the separately built report viewer with a native plugin export on loopback only."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connection', type=Path, required=True)
    args = parser.parse_args()
    connection = json.loads(args.connection.read_text())
    url = connection['url']
    assert urlparse(url).hostname in ('127.0.0.1', 'localhost'), 'Loopback targets only'
    evidence = args.connection.parent
    errors, external, checks = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: external.append(request.url) if urlparse(request.url).scheme in ('http', 'https') and urlparse(request.url).hostname not in ('127.0.0.1', 'localhost') else None)
        page.goto(url)
        expect(page.locator('.pv-card')).to_be_visible(timeout=30000)
        expect(page.get_by_role('button', name='Start the tour', exact=True)).to_be_visible()
        assert page.locator('canvas').count() >= 1
        page.screenshot(path=str(evidence / 'viewer-welcome.png'))
        checks.append('Built viewer accepts and renders the native plugin export')
        steps = page.locator('.pv-dots button').count()
        assert steps >= 5, steps
        for index in range(1, steps):
            page.locator('.pv-card-nav .pv-btn.primary').click()
            expect(page.locator('.pv-step')).to_contain_text(f'Step {index + 1} of {steps}')
            if index == 2:
                page.wait_for_timeout(600)
                page.screenshot(path=str(evidence / 'viewer-map.png'))
        checks.append(f'All {steps} guided tour steps are reachable through the primary action')
        last_hash = page.evaluate('location.hash')
        page.reload()
        expect(page.locator('.pv-card')).to_be_visible(timeout=30000)
        assert page.evaluate('location.hash') == last_hash
        checks.append('Refresh preserves the current tour step')
        page.set_viewport_size({'width': 390, 'height': 844})
        send = page.get_by_role('button', name='Send my feedback to the team', exact=True)
        page.locator('.pv-card textarea').last.fill('Synthetic local acceptance feedback. No message leaves this computer.')
        send.scroll_into_view_if_needed()
        expect(send).to_be_visible()
        page.screenshot(path=str(evidence / 'viewer-narrow.png'))
        send.click()
        expect(page.get_by_text('Your feedback was sent to the team', exact=False)).to_be_visible(timeout=10000)
        outbox = list((evidence / 'outbox').glob('*.json'))
        assert len(outbox) == 1
        assert json.loads(outbox[0].read_text())['to'] == 'feedback@agency.example'
        checks.append('Narrow viewer submits synthetic feedback into the local outbox only')
        page.route('**/api/r/**/report.json', lambda route: route.fulfill(status=404, body='Access denied'))
        page.reload()
        expect(page.get_by_text('This link is not available. Please request a fresh one.', exact=True)).to_be_visible(timeout=10000)
        checks.append('Unavailable report presents the expected failure state')
        assert not errors, errors
        assert not external, external
        checks.append('No uncaught page errors or third-party browser requests')
        browser.close()
    (evidence / 'viewer-results.json').write_text(json.dumps({'status': 'PASS', 'evidenceClass': 'Chromium with built separate viewer, native synthetic export and local outbox', 'checks': checks, 'errors': errors, 'externalRequests': external}, indent=2) + '\n')
    for name in checks:
        print('[PASS]', name)


if __name__ == '__main__':
    main()
