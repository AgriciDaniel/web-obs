#!/usr/bin/env python3
"""Publish dialog with the create-a-profile form, in a real browser (headless Chrome via Playwright), with mock plugin actions.

Checks the layout (compact: the whole dialog shows in a 700 px high pane when the form is closed; the buttons stay visible, the body scrolls when the form is open; three-column color grid on a normal width and one column on a narrow one) and the flow
(Save profile and publish saves BEFORE it publishes; Send with Default look never saves; a failed or refused save never publishes;
the color pickers stay in step with the hex boxes; the notes sit next to the field they belong to). Synthetic data only.
Run: python scripts/verify-publish-dialog-ui.py  (needs Playwright with Chromium, or WEB_OBS_CHROME; builds the plugin stylesheet and the harness with node)
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get('WEB_OBS_CHROME')  # optional path to a Chrome or Chromium; by default Playwright's own Chromium is used
failed = 0


def check(name, ok, detail=''):
    global failed
    if not ok:
        failed += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'  ' + str(detail) if detail and not ok else ''}")


out = Path(tempfile.mkdtemp(prefix='wo-dialog-ui-'))
subprocess.run(['node', 'esbuild.config.mjs'], cwd=ROOT, check=True, capture_output=True)  # always rebuild, so the test never reads an old stylesheet
subprocess.run(['node', 'scripts/ui-harness/build.mjs', str(out)], cwd=ROOT, check=True, capture_output=True)
url = 'file:///' + str(out).replace(chr(92), '/') + '/index.html'
LOOK = 'select[aria-label="Look for this report"]'
CLIENT = 'client:example-client.com.json'


def open_form(pg, cfg=None):
    pg.goto(url)
    if cfg:
        pg.evaluate('(c) => Object.assign(window.__cfg, c)', cfg)
    pg.get_by_label('Publish audit').click()
    pg.wait_for_selector(LOOK)
    pg.select_option(LOOK, CLIENT)
    pg.wait_for_selector('.wo-audit-profile')


def calls(pg):
    return pg.evaluate('() => window.__calls.map(c => c.fn).filter(f => !["styleChoices", "previewStyle", "styleDraft"].includes(f))')


def btn(pg, text):
    return pg.locator('.wo-audit-confirm-foot').get_by_role('button', name=text, exact=True)


with sync_playwright() as p:
    b = p.chromium.launch(**({'executable_path': CHROME} if CHROME else {}), headless=True, args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1000, 'height': 700})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))

    print('layout')
    open_form(pg)
    g = pg.evaluate("""() => {
      const dlg = document.querySelector('.wo-audit-confirm'), panel = document.querySelector('.wo-audit-panel'), scroll = dlg.querySelector('.wo-audit-confirm-scroll');
      const foot = dlg.querySelector('.wo-audit-confirm-foot');
      const n = (s) => getComputedStyle(document.querySelector(s)).gridTemplateColumns.split(' ').length;
      const cols = { identity: n('.wo-audit-cells-2'), colors: n('.wo-audit-cells-colors'), fonts: n('.wo-audit-cells-3') };
      return { dlgBottom: dlg.getBoundingClientRect().bottom, panelBottom: panel.getBoundingClientRect().bottom, vh: innerHeight, scrollable: scroll.scrollHeight > scroll.clientHeight,
               footBottom: foot.getBoundingClientRect().bottom, cols, sw: document.documentElement.scrollWidth, iw: innerWidth };
    }""")
    check('the dialog stays inside the panel and the window', g['dlgBottom'] <= g['panelBottom'] + 1 and g['footBottom'] <= g['vh'], g)
    check('the form body scrolls (it is taller than its space)', g['scrollable'], g)
    check('at a normal width the form is compact: two fields in a row for Identity, three color cells per row, three selects in a row for Fonts', g['cols']['identity'] == 2 and g['cols']['colors'] == 3 and g['cols']['fonts'] == 3, g)
    for t in ['Save profile and publish', 'Save profile', 'Send with Default look', 'Cancel']:
        check(f'the button "{t}" is visible without scrolling', btn(pg, t).is_visible() and btn(pg, t).bounding_box()['y'] + btn(pg, t).bounding_box()['height'] <= 700)
    pg.evaluate("document.querySelector('.wo-audit-confirm-scroll').scrollTop = 99999")
    check('after scrolling to the end the Footer field is reachable and labeled Attribution footer', pg.get_by_label('Attribution footer').is_visible() or pg.locator('label', has_text='Attribution footer').first.is_visible())
    check('there is no Footer text label any more', pg.locator('text=Footer text').count() == 0)
    check('the page does not scroll sideways', g['sw'] <= g['iw'])
    pg.screenshot(path=str(out / 'form-scrolled.png'))
    pg.evaluate("document.querySelector('.wo-audit-confirm-scroll').scrollTop = 0")
    pg.screenshot(path=str(out / 'form-top.png'))

    print('explanations and wording')
    txt = pg.inner_text('.wo-audit-profile')
    for s in ['Buttons, the active step and highlights.', 'The expandable sections.', 'The background of cards and panels.', 'Small secondary text', 'The main text color',
              'The line shown below the 3D presentation layer, for example Prepared by Your Agency.', 'never change', 'Heading case', 'browser tab title', 'Identity', 'Colors', 'Fonts']:
        check(f'the form says: {s[:48]}', s.lower() in txt.lower(), txt[:80])
    check('US spelling in the form (no "colour")', 'colour' not in txt.lower())

    print('color pickers')
    pick = pg.locator('input[type=color]')
    check('there is a color picker for each of the 7 color fields (3 colors and 4 text colors)', pick.count() == 7)
    pg.locator('input[type=color]').first.evaluate("(el) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '#ff8800'); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
    check('choosing a color in the picker fills the hex box', pg.get_by_label('Accent', exact=True).first.input_value().lower() == '#ff8800', pg.get_by_label('Accent', exact=True).first.input_value())
    pg.get_by_label('Accent', exact=True).first.fill('#00ff00')
    check('typing a hex moves the picker', pg.locator('input[type=color]').first.input_value() == '#00ff00')
    pg.get_by_label('Accent', exact=True).first.fill('green')
    check('an invalid hex is flagged (aria-invalid) and the picker falls back to its built-in value', pg.get_by_label('Accent', exact=True).first.get_attribute('aria-invalid') == 'true' and pg.locator('input[type=color]').first.input_value() == '#7c5cff')
    check('an invalid color switches both save buttons off, and Send with Default look stays available', btn(pg, 'Save profile and publish').is_disabled() and btn(pg, 'Save profile').is_disabled() and btn(pg, 'Send with Default look').is_enabled())
    pg.get_by_label('Accent', exact=True).first.fill('#2a7fff')
    pg.get_by_label('Card surface (optional)', exact=False).first.fill('#ffffff')
    note = pg.locator('.wo-audit-colorfield', has_text='Card surface').inner_text()
    check('a card color that cannot be read gets its note next to the Card surface field', 'cardText' in note and 'dark text' in note.lower() and '#f4f6fb' in note, note[:260])
    check('and that note uses US spelling', 'colour' not in note.lower())
    check('while a color is unreadable the profile cannot be saved', btn(pg, 'Save profile').is_disabled() and btn(pg, 'Save profile and publish').is_disabled())
    pg.get_by_label('Card surface (optional)', exact=False).first.fill('#1b1d22')
    print('text on cards (light card with dark text, red card, one-click suggestion)')
    pg.get_by_label('Accent', exact=True).first.fill('#5cff8d'); pg.get_by_label('Text on the page', exact=True).fill('#323334')
    pg.get_by_label('Card surface (optional)', exact=False).first.fill('#f7f7f7')
    err = pg.locator('.wo-audit-colorfield', has_text='Card surface').inner_text()
    check('the light card with dark page text is flagged next to Card surface, with both colors, the number and the way out', '#f7f7f7' in err and '1.07:1' in err and 'cardText' in err and '#10131a' in err, err[:300])
    sug = pg.get_by_role('button', name='Use readable text')
    check('Text on cards offers one-click Use readable text with the color and the ratio', sug.count() == 1 and '#10131a' in sug.inner_text() and '17.3:1' in sug.inner_text(), sug.inner_text() if sug.count() else 'no button')
    check('while the card text is empty the save buttons are off', btn(pg, 'Save profile and publish').is_disabled())
    sug.click()
    check('one click fills Text on cards with the readable color', pg.get_by_label('Text on cards', exact=True).input_value() == '#10131a')
    stage_note = pg.locator('.wo-audit-colorfield', has_text='The main text color on the dark page').first.inner_text()
    check('the page text note (not blocking) names the numbers and the color the page will use instead', '#323334' in stage_note and '1.57:1' in stage_note and 'the page uses #' in stage_note, stage_note[:300])
    check('then the problem is gone and the save buttons are on', btn(pg, 'Save profile and publish').is_enabled() and btn(pg, 'Save profile').is_enabled() and pg.locator('.wo-audit-fieldnote.is-error').count() == 0)
    pg.get_by_label('Card surface (optional)', exact=False).first.fill('#d52924')
    pg.get_by_label('Text on cards', exact=True).fill('#323334')
    err2 = pg.locator('.wo-audit-colorfield').filter(has=pg.get_by_label('Text on cards', exact=True)).inner_text()
    check('on the red card, dark Text on cards is refused with both colors, 2.52:1 and a light-text suggestion', '#323334' in err2 and '#d52924' in err2 and '2.52:1' in err2 and 'Use light text on this card, for example #ffffff (5.0:1)' in err2, err2[:320])
    sug2 = pg.get_by_role('button', name='Use readable text')
    check('and the button offers white with its ratio', sug2.count() == 1 and '#ffffff' in sug2.inner_text() and '5.0:1' in sug2.inner_text(), sug2.inner_text() if sug2.count() else 'no button')
    sug2.click()
    check('one click makes the red card readable', pg.get_by_label('Text on cards', exact=True).input_value() == '#ffffff' and btn(pg, 'Save profile and publish').is_enabled())
    pg.get_by_label('Card surface (optional)', exact=False).first.fill('#1b1d22'); pg.get_by_label('Text on cards', exact=True).fill(''); pg.get_by_label('Text on the page', exact=True).fill('')
    pg.get_by_label('Accent', exact=True).first.fill('#2a7fff')

    print('flows')
    open_form(pg)
    pg.get_by_label('Accent', exact=True).first.fill('#e8743b')
    btn(pg, 'Save profile and publish').click(); pg.wait_for_selector('text=Client report published')
    seq = calls(pg)
    check('Save profile and publish saves first and publishes second, once each', seq == ['saveStyleProfile', 'publish'], seq)
    pub = pg.evaluate("window.__calls.find(c => c.fn === 'publish').args")
    check('and it publishes with the SAVED profile, not Default', pub[2] == CLIENT, pub)

    open_form(pg)
    btn(pg, 'Save profile').click(); pg.wait_for_selector('text=Profile saved as clients/example-client.com.json')
    check('Save profile only saves (no publish) and says where the file went', calls(pg) == ['saveStyleProfile'], calls(pg))
    check('and then the saved look is selected, ready for Approve and create report', pg.locator(LOOK).input_value() == CLIENT and pg.get_by_role('button', name='Approve and create report').is_enabled())

    open_form(pg)
    btn(pg, 'Send with Default look').click(); pg.wait_for_selector('text=Client report published')
    seq = calls(pg); pub = pg.evaluate("window.__calls.find(c => c.fn === 'publish').args")
    check('Send with Default look publishes with Default and never saves the form', seq == ['publish'] and pub[2] == 'default', [seq, pub])

    open_form(pg, {'saveResult': {'ok': False, 'code': 'invalid', 'message': 'The profile needs a fix.'}})
    btn(pg, 'Save profile and publish').click(); pg.wait_for_selector('text=The profile needs a fix.')
    check('if the save fails, nothing is published', calls(pg) == ['saveStyleProfile'], calls(pg))

    open_form(pg, {'saveResult': {'ok': False, 'code': 'exists', 'message': 'exists'}})
    btn(pg, 'Save profile and publish').click(); pg.wait_for_selector('text=already exists')
    check('an existing file is not replaced silently, and nothing is published while the person decides', calls(pg) == ['saveStyleProfile'], calls(pg))
    pg.evaluate("window.__cfg.saveResult = { ok: true, id: 'client:example-client.com.json' }")
    pg.get_by_role('button', name='Replace the file and publish').click(); pg.wait_for_selector('text=Client report published')
    seq = pg.evaluate("window.__calls.filter(c => ['saveStyleProfile','publish'].includes(c.fn)).map(c => c.fn + ':' + (c.fn === 'saveStyleProfile' ? c.args[3] : c.args[2]))")
    check('after the person confirms, it replaces the file (overwrite true) and then publishes', seq == ['saveStyleProfile:false', 'saveStyleProfile:true', 'publish:client:example-client.com.json'], seq)

    open_form(pg)
    pg.get_by_label('Approved by').fill('')
    check('without Approved by, no button that publishes is enabled (saving alone still is)', btn(pg, 'Save profile and publish').is_disabled() and btn(pg, 'Send with Default look').is_disabled() and btn(pg, 'Save profile').is_enabled())
    pg.get_by_label('Approved by').fill('Tester')
    pg.get_by_role('button', name='Cancel').first.click()
    check('Cancel returns to the dialog on Default and nothing was saved or published', pg.locator(LOOK).input_value() == 'default' and calls(pg) == [], calls(pg))

    print('the default look (setting) and editing saved profiles')
    def open_dialog(cfg=None, saved=False, width=1000):
        p = b.new_page(viewport={'width': width, 'height': 860})
        p.on('pageerror', lambda e: errs.append(str(e)))
        p.goto(url); p.evaluate('(c) => { Object.assign(window.__cfg, c.cfg); window.__saved = c.saved; }', {'cfg': cfg or {}, 'saved': saved})
        p.get_by_label('Publish audit').click(); p.wait_for_selector(LOOK); p.wait_for_timeout(200)
        return p
    def sel(p): return p.locator(LOOK).input_value()
    def why_text(p): return p.locator('.wo-audit-confirm-small').first.inner_text() if p.locator('.wo-audit-confirm-small').count() else ''
    for name, cfg, saved, want, phrase in [
        ('auto, client and agency exist', {'agencyExists': True}, True, CLIENT, 'a client profile is named after this site'),
        ('auto, only the agency exists', {'agencyExists': True}, False, 'agency', 'no client profile for this site, so the Agency profile is used'),
        ('auto, nothing exists', {}, False, 'default', 'No client or Agency profile yet'),
        ('setting Agency, both exist', {'agencyExists': True, 'preference': 'agency'}, True, 'agency', 'your setting is the Agency profile'),
        ('setting Agency, none exists', {'preference': 'agency'}, False, 'default', 'none yet'),
        ('setting Default look, both exist', {'agencyExists': True, 'preference': 'default'}, True, 'default', 'your setting is Default look'),
        ('setting Remember my last choice, last was Default', {'agencyExists': True, 'preference': 'last'}, True, 'default', 'last time'),
    ]:
        p = open_dialog(cfg, saved)
        check(f'the look that opens first, {name}: {want}', sel(p) == want, sel(p))
        check(f'and the one-line note says why ({phrase})', phrase.lower() in p.inner_text('.wo-audit-confirm').lower(), p.inner_text('.wo-audit-confirm')[:300])
        check(f'and the select stays visible and changeable', p.locator(LOOK).is_visible() and p.locator(LOOK).is_enabled())
        p.close()

    pe = open_dialog({'agencyExists': True}, False)
    pe.select_option(LOOK, 'default')
    check('a Look that is not set up yet has no Edit button (it opens the create form instead)', pe.get_by_role('button', name='Edit profile').count() == 0)
    pe.select_option(LOOK, 'agency')
    check('a saved profile shows Edit profile next to the Look, and there is no Duplicate action anywhere in the dialog', pe.get_by_role('button', name='Edit profile').is_visible() and 'duplicate' not in pe.inner_text('.wo-audit-confirm').lower())
    pe.get_by_role('button', name='Edit profile').click(); pe.wait_for_selector('.wo-audit-profile')
    check('Edit opens the same form prefilled from the saved file, card text included', pe.get_by_label('Name', exact=True).input_value() == 'Example Agency' and pe.get_by_label('Text on cards', exact=True).input_value() == '#222222' and pe.get_by_label('Attribution footer').input_value() == 'Prepared by Example Agency' and pe.get_by_label('Card surface (optional)', exact=False).first.input_value() == '#f7f7f7')
    check('it says it is editing the saved profile and that a .bak copy is kept', 'Editing the saved agency profile' in pe.inner_text('.wo-audit-profile') and '.bak' in pe.inner_text('.wo-audit-profile'))
    check('the buttons are Save changes and publish, Save changes (off until something changes), Cancel', btn(pe, 'Save changes and publish').is_visible() and btn(pe, 'Save changes').is_disabled() and btn(pe, 'Cancel').is_visible() and pe.get_by_role('button', name='Save profile and publish').count() == 0)
    pe.get_by_label('Accent', exact=True).first.fill('#2a7fff')
    check('after a change Save changes is on', btn(pe, 'Save changes').is_enabled())
    pe.evaluate("window.__calls.length = 0")
    btn(pe, 'Save changes').click(); pe.wait_for_selector('text=Changes saved to agency.json')
    sc = pe.evaluate("window.__calls.filter(c => c.fn === 'saveStyleEdit').map(c => c.args)")
    check('Save changes asks the plugin to save only the changed field, against the file hash it opened', len(sc) == 1 and sc[0][0] == 'agency' and json.loads(sc[0][1]) == ['accent'] and sc[0][2] == 'h1', sc)
    check('it says the previous version is kept as a .bak copy, and nothing was published', '.bak' in pe.inner_text('.wo-audit-confirm-scroll') and 'publish' not in [c for c in calls(pe) if c == 'publish'])
    pe.close()

    pe = open_dialog({'agencyExists': True}, False); pe.select_option(LOOK, 'agency'); pe.get_by_role('button', name='Edit profile').click(); pe.wait_for_selector('.wo-audit-profile')
    pe.get_by_label('Accent', exact=True).first.fill('#2a7fff'); pe.evaluate("window.__calls.length = 0")
    btn(pe, 'Save changes and publish').click(); pe.wait_for_selector('text=Client report published')
    check('Save changes and publish saves first and publishes second, with the saved profile', calls(pe) == ['saveStyleEdit', 'publish'] and pe.evaluate("window.__calls.find(c => c.fn === 'publish').args[2]") == 'agency', calls(pe))
    pe.close()

    pe = open_dialog({'agencyExists': True, 'editResult': {'ok': False, 'code': 'changed', 'message': 'The profile file changed since you opened it. Close this and open it again so nothing is lost.'}}, False)
    pe.select_option(LOOK, 'agency'); pe.get_by_role('button', name='Edit profile').click(); pe.wait_for_selector('.wo-audit-profile'); pe.get_by_label('Accent', exact=True).first.fill('#2a7fff'); pe.evaluate("window.__calls.length = 0")
    btn(pe, 'Save changes and publish').click(); pe.wait_for_selector('text=changed since you opened it')
    check('if the save does not happen (the file changed meanwhile) nothing is published and the reason is shown', calls(pe) == ['saveStyleEdit'], calls(pe))
    pe.close()

    pe = open_dialog({'agencyExists': True}, False); pe.select_option(LOOK, 'agency'); pe.get_by_role('button', name='Edit profile').click(); pe.wait_for_selector('.wo-audit-profile')
    pe.get_by_label('Text on cards', exact=True).fill('#f0f0f0')
    err = pe.locator('.wo-audit-colorfield').filter(has=pe.get_by_label('Text on cards', exact=True)).inner_text()
    check('while editing, the same checks and readable-text help apply: unreadable card text is flagged with the numbers and offers Use readable text', 'reaches only' in err and pe.get_by_role('button', name='Use readable text').count() == 1, err[:200])
    check('and the save buttons are off', btn(pe, 'Save changes').is_disabled() and btn(pe, 'Save changes and publish').is_disabled())
    pe.get_by_role('button', name='Use readable text').click()
    check('one click fixes it', btn(pe, 'Save changes').is_enabled())
    pe.evaluate("window.__calls.length = 0")
    btn(pe, 'Cancel').click()
    check('Cancel with unsaved changes asks first (nothing is saved)', pe.get_by_text('You have unsaved changes').count() == 1 and calls(pe) == [])
    pe.get_by_role('button', name='Keep editing').click()
    check('Keep editing returns to the form with the changes', pe.get_by_label('Text on cards', exact=True).input_value() != '#222222' and pe.locator('.wo-audit-profile').is_visible())
    pe.locator(LOOK).select_option('default')
    check('picking another look with unsaved changes asks first too', pe.get_by_text('You have unsaved changes').count() == 1 and pe.locator('.wo-audit-profile').is_visible())
    pe.get_by_role('button', name='Discard changes').click()
    check('Discard changes leaves the form and goes to that look; nothing was saved', pe.locator('.wo-audit-profile').count() == 0 and sel(pe) == 'default' and 'saveStyleEdit' not in calls(pe), calls(pe))
    pe.select_option(LOOK, 'agency'); pe.get_by_role('button', name='Edit profile').click(); pe.wait_for_selector('.wo-audit-profile'); btn(pe, 'Cancel').click()
    check('Cancel without changes returns at once, to the same look', pe.locator('.wo-audit-profile').count() == 0 and sel(pe) == 'agency' and pe.get_by_text('You have unsaved changes').count() == 0)
    pe.close()

    pe = open_dialog({'agencyExists': True, 'editFail': 'The profile file is not valid JSON, so it cannot be edited here.'}, False); pe.select_option(LOOK, 'agency'); pe.get_by_role('button', name='Edit profile').click()
    pe.wait_for_selector('text=not valid JSON')
    check('a file that cannot be read shows a plain message and no form', pe.locator('.wo-audit-profile').count() == 0 and pe.get_by_text('not valid JSON').is_visible())
    pe.close()

    print('narrow width')
    pg2 = b.new_page(viewport={'width': 420, 'height': 760})
    pg2.on('pageerror', lambda e: errs.append(str(e)))
    open_form(pg2)
    n = pg2.evaluate("""() => ({ cols: getComputedStyle(document.querySelector('.wo-audit-cells-colors')).gridTemplateColumns.split(' ').length, sw: document.documentElement.scrollWidth, iw: innerWidth,
                                 foot: document.querySelector('.wo-audit-confirm-foot').getBoundingClientRect().bottom, vh: innerHeight })""")
    check('on a narrow dialog every group is one column, with no sideways scroll, and the buttons are still visible', n['cols'] == 1 and n['sw'] <= n['iw'] and n['foot'] <= n['vh'], n)
    pg2.screenshot(path=str(out / 'form-narrow.png'))

    print('archive dialog')
    pg3 = b.new_page(viewport={'width': 1000, 'height': 700})
    pg3.goto(url); pg3.get_by_label('Archive audit').click(); pg3.wait_for_selector('.wo-audit-confirm')
    check('the archive dialog still opens (with its own scrolling body)', pg3.locator('.wo-audit-confirm-scroll').count() == 1)

    print('themes, contrast, focus and keyboard (dark and light, 1000 and 420 px wide)')
    JS_CONTRAST = """() => {
      const parse = (s) => { const n = (s.match(/[0-9.]+/g) || []).map(Number); if (s.startsWith('color(')) return { r: n[0] * 255, g: n[1] * 255, b: n[2] * 255, a: n.length > 3 ? n[3] : 1 }; return { r: n[0], g: n[1], b: n[2], a: n.length > 3 ? n[3] : 1 }; };
      const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const blend = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
      const bgOf = (el) => { const chain = []; for (let e = el; e; e = e.parentElement) chain.push(parse(getComputedStyle(e).backgroundColor)); let acc = { r: 255, g: 255, b: 255, a: 1 }; for (let i = chain.length - 1; i >= 0; i--) acc = chain[i].a > 0 ? blend(chain[i], acc) : acc; return acc; };
      const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      const dlg = document.querySelector('.wo-audit-confirm'); const worst = [];
      for (const el of dlg.querySelectorAll('h2, h3, h4, p, label, legend, small, dt, dd, li, a, code, button, span, b, summary')) {
        if (!el.childNodes.length || ![...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
        const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) continue;
        if (el.disabled || (el.closest('button') && el.closest('button').disabled)) continue;
        const cs = getComputedStyle(el); const fg = parse(cs.color); const bg = bgOf(el); const fgb = blend(fg, bg);
        worst.push({ t: el.textContent.trim().slice(0, 28), ratio: Math.round(ratio(fgb, bg) * 100) / 100 });
      }
      worst.sort((a, b) => a.ratio - b.ratio); return worst.slice(0, 3);
    }"""
    for theme in ('dark', 'light'):
        for (w, h) in ((1000, 780), (420, 860)):
            tp = b.new_page(viewport={'width': w, 'height': h})
            tp.on('pageerror', lambda e: errs.append(str(e)))
            tp.goto(f'{url}?theme={theme}')
            tp.get_by_label('Publish audit').click(); tp.wait_for_selector(LOOK)
            tag = f'{theme} {w}px'
            check(f'{tag}: the dialog takes its colors from the Obsidian theme (background is the theme background)', tp.evaluate("() => getComputedStyle(document.querySelector('.wo-audit-confirm')).backgroundColor") == ('rgb(255, 255, 255)' if theme == 'light' else 'rgb(30, 30, 30)'))
            ab = tp.get_by_label('Approved by').bounding_box(); lb = tp.locator(LOOK).bounding_box()
            if w >= 700:
                check(f'{tag}: on the first screen Approved by and the Look selector sit side by side in two columns', lb['x'] >= ab['x'] + ab['width'] - 2 and abs(lb['y'] - ab['y']) < 14, [ab, lb])
            else:
                check(f'{tag}: in a narrow dialog Approved by and the Look selector stack in one column', lb['y'] >= ab['y'] + ab['height'] and abs(lb['x'] - ab['x']) < 4, [ab, lb])
            labs = tp.evaluate("() => ['Approved by', 'Look'].map((n) => { const l = [...document.querySelectorAll('.wo-audit-confirm label')].find((x) => x.textContent.trim() === n); const c = document.getElementById(l.htmlFor); return { n, above: l.getBoundingClientRect().bottom <= c.getBoundingClientRect().top + 1 }; })")
            check(f'{tag}: each label stays above its control', all(x['above'] for x in labs), labs)
            tp.get_by_label('Approved by').focus(); tp.keyboard.press('Tab')
            check(f'{tag}: Tab moves from Approved by to the Look selector (focus order kept)', tp.evaluate("() => document.activeElement && document.activeElement.getAttribute('aria-label')") == 'Look for this report')
            sizes = tp.evaluate("() => { const d = document.querySelector('.wo-audit-confirm'); const s = d.querySelector('.wo-audit-confirm-scroll'); const small = [...d.querySelectorAll('button, input[type=text], select, summary')].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 27.5; }).map((e) => (e.textContent || e.tagName).trim().slice(0, 20)); return { h: Math.round(d.getBoundingClientRect().height), bottom: Math.round(d.getBoundingClientRect().bottom), scrolls: s.scrollHeight > s.clientHeight + 1, small }; }")
            check(f'{tag}: with the form closed the whole dialog is compact and shows without scrolling (no body scroll, under 300 px high on a wide pane)', not sizes['scrolls'] and (sizes['h'] < 300 or w < 700), sizes)
            check(f'{tag}: no control is smaller than 28 px high (touch targets)', not sizes['small'], sizes['small'])
            if w >= 700:
                tp.set_viewport_size({'width': w, 'height': 700}); tp.wait_for_timeout(150)
                s700 = tp.evaluate("() => { const d = document.querySelector('.wo-audit-confirm'); const s = d.querySelector('.wo-audit-confirm-scroll'); return { bottom: Math.round(d.getBoundingClientRect().bottom), vh: innerHeight, scrolls: s.scrollHeight > s.clientHeight + 1 }; }")
                check(f'{tag}: in a pane about 700 px high the whole dialog shows with the form closed (no scrolling)', s700['bottom'] <= 700 and not s700['scrolls'], s700)
                tp.set_viewport_size({'width': w, 'height': h})
            tp.select_option(LOOK, CLIENT); tp.wait_for_selector('.wo-audit-profile')
            low = tp.evaluate(JS_CONTRAST)
            check(f'{tag}: every text in the dialog and the form reads at 4.5:1 or better', all(x['ratio'] >= 4.5 for x in low), low)
            ov = tp.evaluate("() => ({ page: document.documentElement.scrollWidth <= innerWidth, body: (() => { const s = document.querySelector('.wo-audit-confirm-scroll'); return s.scrollWidth <= s.clientWidth + 1; })(), foot: (() => { const f = document.querySelector('.wo-audit-confirm-foot'); return [...f.querySelectorAll('button')].every((x) => x.getBoundingClientRect().right <= f.getBoundingClientRect().right + 1); })() })")
            check(f'{tag}: nothing overflows sideways (page, scrolling body, button row)', all(ov.values()), ov)
            prim = tp.evaluate("() => { const p = document.querySelector('.wo-audit-confirm-foot .is-primary'), s = [...document.querySelectorAll('.wo-audit-confirm-foot .wo-audit-button')].find((x) => !x.classList.contains('is-primary')); const a = getComputedStyle(p), c = getComputedStyle(s); return { pbg: a.backgroundColor, sbg: c.backgroundColor, pw: a.fontWeight }; }")
            check(f'{tag}: the main action is filled and the secondary buttons are not', prim['pbg'] != prim['sbg'] and int(prim['pw']) >= 600, prim)
            tp.get_by_label('Approved by').fill('')
            rs = tp.evaluate("() => { const r = document.querySelector('.wo-audit-reason'); const p = document.querySelector('.wo-audit-confirm-foot .is-primary'); return { text: r ? r.textContent : '', described: p.getAttribute('aria-describedby') === (r ? r.id : 'none'), disabled: p.disabled }; }")
            check(f'{tag}: a disabled main button shows its reason and points to it for screen readers', rs['disabled'] and 'Approved by' in rs['text'] and rs['described'], rs)
            tp.get_by_label('Approved by').fill('Tester')
            tp.get_by_label('Approved by').focus(); tp.keyboard.press('Tab')
            ring = tp.evaluate("() => { const e = document.activeElement; const s = getComputedStyle(e); return { tag: e.tagName, style: s.outlineStyle, width: s.outlineWidth }; }")
            check(f'{tag}: the focused control shows a clear focus ring when tabbing', ring['style'] != 'none' and float(ring['width'].replace('px', '')) >= 2, ring)
            names = tp.evaluate("() => { const d = document.querySelector('.wo-audit-confirm'); return { role: d.getAttribute('role'), title: d.getAttribute('aria-label') || '', unlabeled: [...d.querySelectorAll('input, select, button')].filter((e) => !(e.getAttribute('aria-label') || (e.labels && e.labels.length) || e.textContent.trim())).length }; }")
            check(f'{tag}: the dialog has a name, and every field and button has a label', names['role'] == 'dialog' and 'Publish' in names['title'] and names['unlabeled'] == 0, names)
            tp.keyboard.press('Escape'); tp.wait_for_timeout(150)
            check(f'{tag}: Escape closes the dialog', tp.locator('.wo-audit-confirm').count() == 0)
            tp.get_by_label('Archive audit').click(); tp.wait_for_selector('text=Site name')
            low2 = tp.evaluate(JS_CONTRAST)
            check(f'{tag}: the archive dialog reads at 4.5:1 or better too', all(x['ratio'] >= 4.5 for x in low2), low2)
            tp.close()

    check('no page errors', not errs, errs[:2])
    b.close()

shots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if shots:
    shots.mkdir(parents=True, exist_ok=True)
    for f in out.glob('*.png'):
        shutil.copy(f, shots / f.name)
shutil.rmtree(out, ignore_errors=True)
print('[PASS] Publish dialog UI verified.' if not failed else f'[FAIL] {failed} check(s) failed.')
sys.exit(1 if failed else 0)
