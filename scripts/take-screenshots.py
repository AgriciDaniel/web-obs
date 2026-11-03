#!/usr/bin/env python3
"""Take README screenshots of the standalone Web-Obs app from a saved capture.
Usage: engine/.venv/bin/python3 scripts/take-screenshots.py --site agricidaniel.com
Starts vite on a free port, makes no public requests, writes PNGs to docs/screenshots/."""
import argparse, socket, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from browser_runtime import resolve_chromium_executable


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', default='agricidaniel.com')
    ap.add_argument('--out', type=Path, default=ROOT / 'docs' / 'screenshots')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    vite = subprocess.Popen(['npx', 'vite', '--port', str(port), '--strictPort', '--host', '127.0.0.1'],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1); break
            except Exception:
                time.sleep(0.5)
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, executable_path=resolve_chromium_executable(p)['executablePath'],
                                  args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            page = b.new_page(viewport=dict(width=1440, height=900), device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}/')
            sel = page.get_by_label('Captured websites', exact=True)
            sel.wait_for()
            page.wait_for_timeout(2500)
            sel.select_option(a.site)
            page.wait_for_timeout(2500)
            chosen = sel.evaluate('e => e.options[e.selectedIndex].text')
            assert chosen.startswith(a.site), f'Wrong site selected: {chosen}'
            page.wait_for_timeout(5000)

            def shot(name):
                page.wait_for_timeout(1800)
                page.screenshot(path=str(a.out / f'{name}.png'))
                print('saved', name)

            shot('globe-dark')
            page.get_by_role('tab', name='Road', exact=True).click(); shot('road-dark')
            page.get_by_role('tab', name='Clusters', exact=True).click(); shot('clusters-dark')
            page.get_by_role('tab', name='Globe', exact=True).click()
            page.get_by_role('button', name='Site Intel', exact=True).click(); shot('site-intel-dark')
            page.keyboard.press('Escape')
            page.get_by_role('button', name='Site audit', exact=True).click(); shot('site-audit-dark')
            page.get_by_role('button', name='Close audit', exact=True).click()
            page.get_by_role('button', name='Toggle light/dark theme').click()
            page.wait_for_timeout(3500)
            shot('globe-light')
            print('page errors:', errors)
            b.close()
    finally:
        vite.terminate()


main()
