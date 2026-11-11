// Checks for a client report that carries a look (flat styles) and for the paired upload: the checked copy of the shared styles code, the report the
// exporter writes with a look, the contract and the seal, and the https publish that sends ONE request with two named parts (styles_<hash> and data_<hash>).
// Synthetic data only; no network and no real secret.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { build } from 'esbuild';

let n = 0;
const ok = (name, fn) => Promise.resolve(fn()).then(() => { n++; console.log('  ok   ' + name); });
async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-report-look-'));

// ---- stage 1: the shared styles code is a checked copy of the report app's ----
const { validateStyles, suggestCardText, deriveStyleOutput } = await import('../src/report/styles/styles.mjs');
const { contrast, mix, STAGE_BG } = await import('../src/report/styles/color.mjs');
const { stylesHash, makeEnvelope } = await import('../src/report/styles/styles-hash.mjs');
const SHA = {
  'color.mjs': '429c8190d67287295c469d6cfdf29b1a247aa8751ff27bf8029e94ab9d6c86c3',
  'styles.mjs': '9fe38cdc31682188dbddddee8780489c860da6b6e38cc5f9dfd927898cfa5ad0',
  'styles-hash.mjs': '86abbb1ae3a63a0deed80f6008b135ed80644153537da43941aadcb212858d60',
};
// Where the three copies come from. The hashes above catch an edit here; this names what they were copied from, so drift from the report app can be seen by
// comparing against that commit. (The report app repository is private: gcollins808/web-obs-client-report.)
const SOURCE = { app: 'web-obs-client-report', version: '0.1.7', tag: 'v0.1.7', commit: '65eccc7c902fb8ce525719e3a8a0d846b842d1bb', folder: 'apps/viewer/brand', files: Object.keys(SHA) };
console.log('the shared styles code');
await ok('the copies name their source (report app version, tag, commit and paths), and the docs and the README of the copy name the same version and commit', () => {
  assert.match(SOURCE.commit, /^[0-9a-f]{40}$/); assert.equal(SOURCE.tag, 'v' + SOURCE.version); assert.deepEqual(SOURCE.files, ['color.mjs', 'styles.mjs', 'styles-hash.mjs']);
  const readme = fs.readFileSync(path.join('src', 'report', 'styles', 'README.md'), 'utf8'), docs = fs.readFileSync(path.join('docs', 'PUBLISH-STYLES.md'), 'utf8');
  for (const [name, text] of [['README', readme], ['PUBLISH-STYLES', docs]]) { assert.ok(text.includes(SOURCE.version), name + ' names the version'); assert.ok(text.includes(SOURCE.commit.slice(0, 12)), name + ' names the commit'); assert.ok(text.includes(SOURCE.folder), name + ' names the folder'); }
});
await ok('the three shared modules match the report app files (sha256), so a copy that drifts fails here', () => {
  for (const [f, h] of Object.entries(SHA)) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join('src', 'report', 'styles', f), 'utf8').split(String.fromCharCode(13, 10)).join(String.fromCharCode(10))).digest('hex'), h, f); // line endings
});
const LOOK = { accent: '#f2994a', secondary: '#2ecdf5', link: '#23aeeb', text: '#c4c4c4', muted: '#9aa3b5', surface: '#101010', headingFont: 'Oswald', bodyFont: 'Inter', headingCase: 'uppercase', name: 'Example Agency', footerText: 'Prepared by Example Agency' };
await ok('a flat look is accepted and comes back as a fresh object holding only checked values', () => {
  const v = validateStyles(LOOK); assert.equal(v.ok, true, v.errors.join(' ')); assert.notEqual(v.styles, LOOK); assert.deepEqual(v.styles, LOOK);
});
await ok('a typo, a bad color, hostile text and a look no card text can read are refused with a plain message, and nothing throws', () => {
  assert.match(validateStyles({ acent: '#ffffff' }).errors.join(' '), /acent/);
  assert.equal(validateStyles({ accent: 'red' }).ok, false);
  assert.equal(validateStyles({ name: 'a\u0000b' }).ok, false);
  assert.equal(validateStyles({ bg: '#000000' }).ok, false, 'there is no slot for the page background');
  assert.match(validateStyles({ surface: '#f7f7f7', text: '#323334' }).errors.join(' '), /surface/);
  assert.match(validateStyles({ surface: '#d52924', cardText: '#323334' }).errors.join(' '), /2\.52:1/);
  assert.equal(suggestCardText('#d52924').color, '#ffffff');
  for (const bad of [null, undefined, 5, 'x', [], JSON.parse('{"__proto__": {"x": 1}}'), { name: 'x'.repeat(5000) }]) assert.doesNotThrow(() => validateStyles(bad));
});
await ok('the copy has the 0.1.7 card behavior: a light card is drawn opaque, a red card with only a card color gets readable built in colors, and every text color reads on the card as drawn', () => {
  const alpha = (v) => { const m = /rgba\([^)]*,\s*([0-9.]+)\)\s*$/.exec(v || ''); return m ? Number(m[1]) : 1; };
  const light = validateStyles({ accent: '#1a6fd0', surface: '#f7f7f7', cardText: '#323334', text: '#e6e6e6', muted: '#9aa3b5' }); assert.ok(light.ok, light.errors.join(' '));
  const lv = deriveStyleOutput(light.styles).vars; assert.equal(lv['--panel'], '#f7f7f7'); assert.equal(lv['--rp-card-glass'], '#f7f7f7');
  const red = validateStyles({ surface: '#d52924', text: '#ffffff' }); assert.ok(red.ok, red.errors.join(' ')); const rv = deriveStyleOutput(red.styles).vars;
  for (const [what, c] of [['muted text', rv['--rp-card-muted']], ['second color', rv['--rp-secondary']], ['link', rv['--rp-link']]]) assert.ok(contrast(c, '#d52924') >= 4.5, what);
  assert.ok(alpha(rv['--panel']) < 1, 'a mid-tone card with light text keeps the glass look');
  const card = mix(STAGE_BG, '#d52924', alpha(rv['--panel'])); assert.ok(contrast(rv['--rp-card-ink'] || '#ffffff', card) >= 4.5, 'the card text reads on the card as drawn');
});
await ok('the pairing name is the same whatever the key order, and the envelope has exactly styles_<hash> and data_<hash>', () => {
  assert.equal(stylesHash({ accent: '#f2994a', name: 'A' }), stylesHash({ name: 'A', accent: '#f2994a' }));
  const e = makeEnvelope({ format: 'webobs.client-report' }, LOOK); const keys = Object.keys(e);
  assert.equal(keys.length, 2); assert.equal(keys[0].slice(7), keys[1].slice(5)); assert.equal(keys[0].slice(7), stylesHash(LOOK));
});

// ---- stage 2: the report carries an optional look; the contract and the seal ----
const { exportClientReport } = await load('src/report/exportAudit.ts');
const { PREVIEW_SITE_MANIFEST } = await load('src/data/demoSite.ts');
const { reportValueProblems } = await load('src/report/contractValues.ts');
const { REPORT_FIELDS } = await load('src/report/contract.ts');
const { validateClientReport } = await load('src/report/package.ts');
const manifest = structuredClone(PREVIEW_SITE_MANIFEST);
const AT = '2026-01-01T00:00:00.000Z';
const withLook = await exportClientReport(manifest, { approvedBy: 'Test Approver', createdAt: AT, styles: LOOK });
const plain = await exportClientReport(manifest, { approvedBy: 'Test Approver', createdAt: AT });
console.log('the report with a look');
await ok('the exporter puts the checked look in the report; without one the report has no styles field; a bad look stops the export', async () => {
  const r = JSON.parse(withLook.json); assert.equal(r.styles.accent, '#f2994a'); assert.equal(r.styles.name, 'Example Agency'); assert.ok(!('styles' in JSON.parse(plain.json)));
  await assert.rejects(() => exportClientReport(manifest, { approvedBy: 'x', styles: { accent: 'red' } }), /The look is not valid/);
  await assert.rejects(() => exportClientReport(manifest, { approvedBy: 'x', styles: { bg: '#000000' } }), /The look is not valid/);
});
await ok('the contract names the styles field, checks every slot of it, and a report with a look passes the package check', () => {
  assert.ok(REPORT_FIELDS.includes('styles'));
  const r = JSON.parse(withLook.json);
  assert.deepEqual(reportValueProblems(r), []); assert.deepEqual(validateClientReport(r), []);
  for (const bad of [{ accent: 'red' }, { bg: '#000000' }, { headingFont: 'Comic Sans' }, { name: 'x'.repeat(500) }]) assert.ok(reportValueProblems({ ...r, styles: bad }).some((p) => /^styles/.test(p.where)), JSON.stringify(bad));
});
await ok('the seal does not depend on the look: the same report sealed with and without a look has the same hash, and a seal check that drops styles passes', () => {
  const a = JSON.parse(withLook.json), b = JSON.parse(plain.json);
  assert.equal(a.meta.integrity.contentSha256, b.meta.integrity.contentSha256);
  const { styles, ...rest } = a; void styles; const body = { ...rest, meta: { ...a.meta, integrity: undefined } };
  assert.equal(crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex'), a.meta.integrity.contentSha256);
});

// ---- stage 3: the https publish sends a report with a look as two named parts ----
const { publishToTarget, parsePublishTarget, OLD_SERVER_HINT } = await load('src/plugin/publishTarget.ts');
const SECRET = 'app-secret-' + 'a'.repeat(30);
const target = parsePublishTarget('audit.example.com');
const sent = []; const post = (reply) => async (url, headers, body) => { sent.push({ url, headers, body }); return reply; };
const created = { status: 201, body: JSON.stringify({ ok: true, link: 'https://audit.example.com/r/abc', linkId: '0123456789', expiresAt: '2030-01-01T00:00:00Z' }) };
console.log('the paired upload');
await ok('a report with a look is sent as ONE request: exactly styles_<hash> and data_<hash>, same hash, data part without the styles', async () => {
  const r = await publishToTarget(target, withLook.json, { hours: 72, deps: { secret: () => SECRET, post: post(created) } });
  assert.equal(r.link, 'https://audit.example.com/r/abc');
  const body = JSON.parse(sent[0].body); const keys = Object.keys(body); assert.equal(keys.length, 2);
  const s = keys.find((k) => k.startsWith('styles_')), d = keys.find((k) => k.startsWith('data_')); assert.ok(s && d);
  assert.equal(s.slice(7), d.slice(5)); assert.equal(s.slice(7), stylesHash(body[s])); assert.equal(body[d].format, 'webobs.client-report'); assert.ok(!('styles' in body[d]));
  assert.equal(sent[0].headers.Authorization, 'Bearer ' + SECRET);
});
await ok('a plain report is sent exactly as it was before: the same body, no envelope', async () => {
  sent.length = 0; await publishToTarget(target, plain.json, { hours: 72, deps: { secret: () => SECRET, post: post(created) } });
  assert.equal(sent[0].body, plain.json);
});
await ok('a server older than 0.1.4 that refuses the two-part request is explained plainly (update the server first), and only for a report with a look', async () => {
  await assert.rejects(() => publishToTarget(target, withLook.json, { hours: 72, deps: { secret: () => SECRET, post: post({ status: 422, body: 'That is not a client report.' }) } }), (e) => e.message === OLD_SERVER_HINT && /0\.1\.4/.test(e.message));
  await assert.rejects(() => publishToTarget(target, plain.json, { hours: 72, deps: { secret: () => SECRET, post: post({ status: 422, body: 'That is not a client report.' }) } }), (e) => e.message !== OLD_SERVER_HINT);
});
await ok('a plain 422 from a newer server is shown to the person (short sentences only)', async () => {
  await assert.rejects(() => publishToTarget(target, withLook.json, { hours: 72, deps: { secret: () => SECRET, post: post({ status: 422, body: 'The styles are not valid: x.' }) } }), /with its look: The styles are not valid/);
});
await ok('bad styles inside a report never leave the computer: no request is made', async () => {
  const r = JSON.parse(withLook.json); r.styles = { accent: 'red' }; sent.length = 0;
  await assert.rejects(() => publishToTarget(target, JSON.stringify(r), { hours: 72, deps: { secret: () => SECRET, post: post(created) } }), /The look is not valid/);
  assert.equal(sent.length, 0);
});
await ok('a folder target stores the report with the look inside it (no envelope); the server checks it again when it serves', async () => {
  const dest = path.join(tmp, 'out'); const r = await publishToTarget({ kind: 'folder', dir: dest }, withLook.json, { hours: 24, linkBase: 'https://r.example.com' });
  assert.match(r.link, /^https:\/\/r\.example\.com\/r\//);
  const files = fs.readdirSync(path.join(dest, 'reports')); assert.equal(files.length, 1);
  assert.equal(JSON.parse(fs.readFileSync(path.join(dest, 'reports', files[0]), 'utf8')).styles.accent, '#f2994a');
});

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`Report look OK: ${n} checks passed.`);
