#!/usr/bin/env python3
"""Renders the states of the Publish and Archive dialogs to PNG files, in a dark and a light theme, at about 1000 px and 420 px wide.
Used for before/after comparisons and for the visual review. Headless Chrome through Playwright; mock plugin actions; synthetic data only.
Run: python scripts/render-publish-dialog-states.py <outdir> [prefix]
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get('WEB_OBS_CHROME')  # optional path to a Chrome or Chromium; by default Playwright's own Chromium is used
outdir = Path(sys.argv[1]); outdir.mkdir(parents=True, exist_ok=True)
prefix = sys.argv[2] if len(sys.argv) > 2 else 'state'
build = Path(tempfile.mkdtemp(prefix='wo-render-'))
subprocess.run(['node', 'esbuild.config.mjs'], cwd=ROOT, check=True, capture_output=True)  # always rebuild, so the test never reads an old stylesheet
subprocess.run(['node', 'scripts/ui-harness/build.mjs', str(build)], cwd=ROOT, check=True, capture_output=True)
base = 'file:///' + str(build).replace(chr(92), '/') + '/index.html'
LOOK = 'select[aria-label="Look for this report"]'
CLIENT = 'client:example-client.com.json'
SIZES = {'1000': (1000, 780), '420': (420, 860)}


def start(pg, theme, cfg=None, saved=False):
    pg.goto(f'{base}?theme={theme}')
    pg.evaluate('(c) => { Object.assign(window.__cfg, c.cfg); window.__saved = c.saved; }', {'cfg': cfg or {}, 'saved': saved})


def open_publish(pg):
    pg.get_by_label('Publish audit').click()
    pg.wait_for_selector(LOOK, timeout=4000) if pg.locator(LOOK).count() or True else None


def shot(pg, theme, size, name):
    pg.wait_for_timeout(250)
    pg.screenshot(path=str(outdir / f'{prefix}-{name}-{theme}-{size}.png'))


with sync_playwright() as p:
    b = p.chromium.launch(**({'executable_path': CHROME} if CHROME else {}), headless=True, args=['--no-sandbox'])
    for theme in ('dark', 'light'):
        for size, (w, h) in SIZES.items():
            pg = b.new_page(viewport={'width': w, 'height': h})
            # 1 ready to publish with the built-in look
            start(pg, theme); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); shot(pg, theme, size, '1-publish')
            # 2 a saved client look is chosen
            start(pg, theme, saved=True); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); pg.wait_for_selector('text=Chosen because'); shot(pg, theme, size, '2-look-chosen')
            # 3 the create-a-profile form, and 4 with a card color that cannot be read
            start(pg, theme); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); pg.select_option(LOOK, CLIENT); pg.wait_for_selector('.wo-audit-profile'); shot(pg, theme, size, '3-form')
            pg.get_by_label('Card surface', exact=False).first.fill('#ffffff'); pg.evaluate("document.querySelector('.wo-audit-confirm-scroll').scrollTop = 520"); shot(pg, theme, size, '4-form-note')
            # 4b text on cards: a light card with dark page text (flagged, with the one-click suggestion), the fix, and a red card with unreadable card text
            def scroll_to_text(): pg.evaluate("document.querySelector('.wo-audit-confirm-scroll').scrollTop = 99999")
            pg.get_by_label('Card surface', exact=False).first.fill('#f7f7f7'); pg.get_by_label('Text on the page', exact=True).fill('#323334'); scroll_to_text(); shot(pg, theme, size, '4b-light-card-flagged')
            pg.get_by_role('button', name='Use readable text').click(); scroll_to_text(); shot(pg, theme, size, '4c-light-card-fixed')
            pg.get_by_label('Card surface', exact=False).first.fill('#d52924'); pg.get_by_label('Text on cards', exact=True).fill('#323334'); scroll_to_text(); shot(pg, theme, size, '4d-red-card-refused')
            # 5 published
            start(pg, theme); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); pg.get_by_role('button', name='Approve and create report').click(); pg.wait_for_selector('text=published'); shot(pg, theme, size, '5-published')
            # 6 a failed publish
            start(pg, theme, cfg={'failPublish': True}); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); pg.get_by_role('button', name='Approve and create report').click(); pg.wait_for_selector('[role=alert]'); shot(pg, theme, size, '6-error')
            # 7 nothing to publish to yet
            start(pg, theme, cfg={'publishReady': False, 'noTarget': True}); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); shot(pg, theme, size, '7-not-ready')
            # 9 a saved look chosen from the Default look setting, 10 Edit profile prefilled, 11 changed and flagged, 12 unsaved-changes guard
            start(pg, theme, cfg={'agencyExists': True}, saved=True); pg.get_by_label('Publish audit').click(); pg.wait_for_selector(LOOK); pg.wait_for_selector('text=Chosen because'); pg.select_option(LOOK, 'agency'); shot(pg, theme, size, '9-saved-look-actions')
            pg.get_by_role('button', name='Edit profile').click(); pg.wait_for_selector('.wo-audit-profile'); shot(pg, theme, size, '10-edit-prefilled')
            pg.get_by_label('Accent', exact=True).first.fill('#2a7fff'); pg.get_by_label('Text on cards', exact=True).fill('#f0f0f0'); pg.evaluate("document.querySelector('.wo-audit-confirm-scroll').scrollTop = 99999"); shot(pg, theme, size, '11-edit-changed-flagged')
            pg.get_by_role('button', name='Cancel').click(); pg.wait_for_selector('text=You have unsaved changes'); shot(pg, theme, size, '12-edit-unsaved-guard')
            # 8 archive
            start(pg, theme); pg.get_by_label('Archive audit').click(); pg.wait_for_selector('text=Type'); shot(pg, theme, size, '8-archive')
            pg.close()
    b.close()
print('rendered', len(list(outdir.glob(f'{prefix}-*.png'))), 'files in', outdir)
