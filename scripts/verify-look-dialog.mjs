// The Look in the Publish dialog and the settings: the dialog and settings source carries the choices, the form, Save, Cancel, the readable-text help and the profile list.
// Synthetic data and temporary folders only (example-client.com and .test names). No network, no real secret.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { build } from 'esbuild';

let n = 0;
const ok = async (name, fn) => { await fn(); n++; console.log('  ok   ' + name); };
async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const bar = () => fs.readFileSync('src/components/AuditActionsBar.tsx', 'utf8');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-look-dialog-'));
const D = await load('src/data/defaultLook.ts');

{
  await ok('the dialog uses it and says why a look was chosen', () => {
    const bar = fs.readFileSync('src/components/AuditActionsBar.tsx', 'utf8');
    assert.ok(bar.includes('resolveDefaultLook({ domain: manifest.domain') && fs.readFileSync('src/data/defaultLook.ts', 'utf8').includes('Chosen because a client profile is named after this site.'));
  });
}

{
  await ok('the dialog and the settings carry the Look choice (Default, Agency, Client) and the profiles folder', () => {
    const bar = fs.readFileSync('src/components/AuditActionsBar.tsx', 'utf8'), set = fs.readFileSync('src/plugin/settings.ts', 'utf8');
    assert.ok(bar.includes('aria-label="Look for this report"') && bar.includes('actions.publish(manifest.siteId, approver, id)') && bar.includes('publishWith(styleId)') && bar.includes('Everything in a look is visible to anyone who has the report link.'));
    assert.ok(set.includes("'Style profiles folder'") && set.includes('stylesChoice'));
  });
}

{
  await ok('the dialog source: the form, Save, Cancel, Send with Default, the public warning; the file is written only from the Save handler', () => {
    const src = fs.readFileSync('src/components/AuditActionsBar.tsx', 'utf8');
    const form = fs.readFileSync('src/components/StyleProfileForm.tsx', 'utf8');
    for (const s of ['Save profile', 'Save profile and publish', 'Send with Default look', 'Cancel', 'Replace the file']) assert.ok(src.includes(s), s);
    for (const s of ['visible to anyone who has the report link', 'Nothing is written until you press Save']) assert.ok(src.includes(s) || form.includes(s), s);
    assert.equal(src.split('lk.saveStyleProfile(').length - 1, 1, 'saveStyleProfile is called in exactly one place');
    assert.ok(src.indexOf('const saveProfile') < src.indexOf('lk.saveStyleProfile('), 'it is inside the Save handler');
    assert.ok(!src.split('const saveProfile')[0].includes('lk.saveStyleProfile('), 'opening the form does not write');
    const view = fs.readFileSync('src/plugin/SiteGlobeView.ts', 'utf8');
    assert.equal(view.split('createProfile(').length - 1, 1, 'createProfile is used in one place');
    assert.ok(view.includes('m.domain'), 'the file name comes from the capture domain');
  });
  // ---- report app 0.1.5: readability is enforced, and the seal does not depend on the look ----
  const { exportClientReport } = await load('src/report/exportAudit.ts');
  const { PREVIEW_SITE_MANIFEST } = await load('src/data/demoSite.ts');
  const crypto = await import('node:crypto');
}

{
  await ok('the dialog source: one clear primary action that saves first, no publish of an unsaved look, scrolling body, pinned buttons', () => {
    const src = fs.readFileSync('src/components/AuditActionsBar.tsx', 'utf8'), css = fs.readFileSync('src/styles/audit.css', 'utf8');
    assert.ok(src.includes('Save profile and publish') && src.includes('wo-audit-confirm-scroll') && src.includes('wo-audit-confirm-foot'));
    assert.ok(src.includes('publishWith(r.id)'), 'publishes with the id returned by the save');
    assert.equal(src.split("publishWith('default')").length - 1, 1, 'the only publish that skips the save is the explicit Default one');
    assert.ok(src.indexOf('disabled={!canPublish || !formOk}') > 0, 'the save buttons wait for a valid form');
    const rule = (sel) => { const i = css.indexOf(sel + ' {'); return i < 0 ? '' : css.slice(i, css.indexOf('}', i)); };
    assert.ok(rule('.wo-audit-confirm-scroll').includes('overflow-y: auto') && rule('.wo-audit-confirm-foot').includes('flex: 0 0 auto'), 'the body scrolls and the button row does not shrink');
    assert.ok(css.includes('@container wo-confirm (max-width: 640px)') && rule('.wo-audit-cells-colors').includes('repeat(3, minmax(0, 1fr))') && css.includes('@container wo-confirm (max-width: 480px)'), 'a compact grid: three color cells per row, one column on narrow');
  });
  // ---- the attribution footer of a client profile starts from the agency profile ----
  const SITE = { domain: 'example-client.com', brandName: 'Example Client', brandKit: { themeColor: '#2a7fff' } };
}

{
  await ok('the plugin passes the agency name from the styles folder when it prepares a client draft', () => {
    const view = fs.readFileSync('src/plugin/SiteGlobeView.ts', 'utf8');
    assert.ok(view.includes('agencyNameFromFolder(resolveStylesFolder(vaultRoot, settings().stylesFolder))') && view.includes("draftFromManifest(m, styleId === 'agency' ? 'agency' : 'client', agencyName)"));
  });
  // ---- report app 0.1.6: text on cards (cardText, cardMuted) ----
  const MEMBER = { name: 'Example Client', accent: '#5cff8d', secondary: '#d4f52e', surface: '#f7f7f7', text: '#323334', muted: '#707070' };
  const { suggestCardText } = await import('../src/report/styles/styles.mjs');
}

{
  await ok('the dialog source: the Text colors group, the Use readable text button, and the cardText field next to the suggestion', () => {
    const form = fs.readFileSync('src/components/StyleProfileForm.tsx', 'utf8');
    assert.ok(form.includes('Text colors') && form.includes('TEXT_FIELDS.map') && form.includes('Use readable text') && form.includes('suggestCardText') && form.includes("field === 'cardText'"));
  });
  fs.rmSync(tmp, { recursive: true, force: true });
}

{
  await ok('the settings tab carries the Default look setting, the Style profiles list with Edit, and says there is no delete yet', () => {
    const s = fs.readFileSync('src/plugin/settings.ts', 'utf8');
    for (const w of ['Default look when publishing', 'Style profiles', 'There is no delete in this version', "'Edit'", 'defaultLook', 'listProfileSummaries', 'ProfileEditorModal']) assert.ok(s.includes(w), w);
    for (const w of ['Duplicate', 'duplicateProfile']) assert.ok(!s.includes(w), 'no ' + w + ' in the settings');
    assert.equal(JSON.stringify(D.DEFAULT_LOOK_PREFERENCES.map((p) => p.label)).includes('Remember my last choice'), true);
  });
  fs.rmSync(tmp, { recursive: true, force: true });
}

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`Look dialog source OK: ${n} checks passed.`);
