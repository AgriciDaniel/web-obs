#!/usr/bin/env python3
"""Render-on-demand regression: a settled map must stop drawing, and hover, selection and resize must still work.

Runs the standalone app in Chromium with explicit software WebGL (SwiftShader). Evidence class: standalone browser,
not native Obsidian and not a GPU measurement.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
INIT = """
(() => {
  window.__p = { draws: 0, dim: 0 };
  for (const C of [WebGL2RenderingContext, WebGLRenderingContext]) {
    for (const f of ['drawElements','drawArrays','drawElementsInstanced','drawArraysInstanced']) {
      const o = C.prototype[f]; if (!o) continue;
      C.prototype[f] = function(...a){ window.__p.draws++; return o.apply(this,a); };
    }
  }
  const ow = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { get() { window.__p.dim++; return ow.get.call(this); }, configurable: true });
})();
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    port = free_port()
    server = subprocess.Popen(['npx', 'vite', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError('Standalone app did not start.')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.add_init_script(INIT)
            page.goto(f'http://127.0.0.1:{port}/')
            page.wait_for_selector('canvas', timeout=30000)
            # A fresh clone has no captures and opens on the welcome screen. Use the built-in sample.
            sample = page.get_by_text('inspect sample 3D Site Globe preview')
            if sample.count():
                sample.click()
            page.wait_for_selector('.wo-canvas-stage', timeout=30000)
            page.wait_for_timeout(5000)

            def counters(ms):
                page.evaluate('() => { window.__p.draws = 0; window.__p.dim = 0; }')
                page.wait_for_timeout(ms)
                return page.evaluate('() => ({ ...window.__p })')

            def pills():
                return page.evaluate("() => [...document.querySelectorAll('.wo-node-pill')].filter(p => !p.classList.contains('is-hidden')).length")

            pulses_on = counters(3000)
            assert pulses_on['dim'] == 0, f'label sizes must not be re-read every frame: {pulses_on}'
            page.get_by_role('button', name='Map layers').click()
            toggle = page.get_by_role('menuitemcheckbox', name='Light flow')
            assert toggle.count(), 'Light flow toggle not found'
            assert toggle.first.get_attribute('aria-checked') == 'true'
            toggle.first.click()
            assert toggle.first.get_attribute('aria-checked') == 'false'
            page.keyboard.press('Escape')
            page.wait_for_timeout(1500)
            settled = counters(3000)
            assert settled['draws'] == 0, f'a settled map with Light Flow off must not draw: {settled}'
            assert settled['dim'] == 0, settled
            rest = pills()
            assert rest > 5, rest

            target = page.evaluate("() => { const p=[...document.querySelectorAll('.wo-node-pill')].find(p => !p.classList.contains('is-hidden') && p.dataset.nodeId); const r=p.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }")
            page.mouse.move(target['x'], target['y'])
            page.wait_for_timeout(1500)
            hover = page.evaluate("() => ({ layer: document.querySelector('.wo-css2d-layer').classList.contains('is-hovering-node'), target: document.querySelectorAll('.wo-node-pill.is-hover-target').length })")
            assert hover['layer'] and hover['target'] == 1, f'hover must highlight exactly one label: {hover}'
            page.mouse.move(3, 3)
            page.wait_for_timeout(1500)
            after = page.evaluate("() => ({ layer: document.querySelector('.wo-css2d-layer').classList.contains('is-hovering-node'), target: document.querySelectorAll('.wo-node-pill.is-hover-target').length })")
            assert not after['layer'] and after['target'] == 0, f'hover must clear: {after}'
            assert pills() == rest, (pills(), rest)
            idle_after = counters(2000)
            assert idle_after['draws'] == 0, f'map must settle again after hover: {idle_after}'

            page.mouse.move(700, 500)
            page.mouse.down()
            page.evaluate('() => { window.__p.draws = 0; }')
            for i in range(30):
                page.mouse.move(700 + i * 6, 500 + i * 2)
                page.wait_for_timeout(60)
            page.mouse.up()
            assert page.evaluate('() => window.__p.draws') > 0, 'dragging the camera must render'

            page.evaluate("() => document.querySelector('.wo-node-pill:not(.is-hidden)').click()")
            page.wait_for_timeout(1200)
            assert page.evaluate("() => document.querySelectorAll('.wo-node-pill.is-active').length") == 1

            page.set_viewport_size({'width': 900, 'height': 700})
            page.wait_for_timeout(2500)
            assert pills() > 3, 'labels must be placed after a resize'
            assert not errors, errors
            browser.close()
        print('[PASS] Render on demand verified: settled maps stop drawing; hover, drag, select and resize still render.')
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    sys.exit(main())
