// Style profiles as files, the profile form and the default look: mapping, bounded reading, the choices, create, edit and the default look decision.
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
const { validateStyles } = await import('../src/report/styles/styles.mjs');

// ---- profile files mapped to flat styles, and the folder they live in ----
{
  const P = await load('src/plugin/stylesProfiles.ts');
  const { profileToStyles, listStyleChoices, loadStyleChoice, resolveStylesFolder, readProfileFile, PROFILE_MAX_BYTES } = P;
  // A synthetic agency profile with the real key names (the voice and similar keys are there on purpose: they must never be sent).
  const AGENCY = {
    name: 'Example Agency', voice_context: 'agency', audience: 'clients', source: 'brand.md',
    colors: { primary: '#23AEEB', blue_dark: '#1879A3', blue_light: '#2ECDF5', tint: '#EAF6FC', accent_orange: '#F2994A', text: '#313131', text_on_dark: '#C4C4C4', grey_1: '#1C1F26', grey_2: '#25272E', surface: '#101010', muted: '#6B6B6B', grid: '#D5D9DE' },
    fonts: { heading: { name: 'Oswald', file: 'Oswald.ttf', case: 'uppercase' }, body: { name: 'Inter', regular: 'Inter-Regular.ttf', bold: 'Inter-SemiBold.ttf' } },
    logo: '(a path)', attribution: { header_text: 'Example Agency', footer_text: 'Prepared by Example Agency' },
    voice: ['Be positive.'], avoid_words: ['bad'], negation_max_per_100_words: 1.6, preferences: { first_person: { report: 'we' } },
  };


  console.log('profiles become flat styles');
  await ok('an agency profile maps to the documented slots, and nothing else leaves (no voice, no avoid_words, no grey_1)', () => {
    const r = profileToStyles(AGENCY);
    assert.deepEqual(r.errors, []);
    assert.deepEqual(r.styles, { accent: '#f2994a', link: '#23aeeb', secondary: '#2ecdf5', text: '#c4c4c4', muted: '#6b6b6b', surface: '#101010', headingFont: 'Oswald', bodyFont: 'Inter', headingCase: 'uppercase', name: 'Example Agency', footerText: 'Prepared by Example Agency' });
    assert.ok(r.notes.some((x) => /grey_0 and grey_1 are reserved/.test(x)));
    assert.ok(!JSON.stringify(r.styles).includes('Be positive') && !JSON.stringify(r.styles).includes('1C1F26'.toLowerCase()));
  });
  await ok('without colors.surface the card color comes from grey_2; without accent_orange the accent is primary', () => {
    const p = structuredClone(AGENCY); delete p.colors.surface; delete p.colors.accent_orange;
    const r = profileToStyles(p); assert.equal(r.styles.surface, '#25272e'); assert.equal(r.styles.accent, '#23aeeb');
  });
  await ok('a font that is not bundled is left out with a note (the system font is used), the rest still works', () => {
    const p = structuredClone(AGENCY); p.fonts.heading.name = 'Comic Sans'; p.fonts.body.name = 'Arial';
    const r = profileToStyles(p); assert.deepEqual(r.errors, []); assert.ok(!('headingFont' in r.styles) && !('bodyFont' in r.styles));
    assert.equal(r.notes.filter((x) => /not bundled/.test(x)).length, 2);
  });
  await ok('an already flat styles file is accepted as it is; a flat file with a typo is refused with the key named', () => {
    assert.deepEqual(profileToStyles({ accent: '#112233', name: 'Flat' }).styles, { accent: '#112233', name: 'Flat' });
    const bad = profileToStyles({ acent: '#112233' }); assert.equal(bad.styles, null); assert.match(bad.errors[0], /"acent"/);
  });
  await ok('bad profiles never throw and never produce styles: wrong types, bad colors, hostile text keys, __proto__, huge values', () => {
    const hostile = [null, 5, 'x', [], { colors: 'red' }, { colors: { primary: 'red' } }, { colors: { primary: '#23AEEB', text_on_dark: 'url(x)' } }, { colors: { primary: '#23AEEB' }, name: '' },
      { colors: { primary: '#23AEEB' }, name: 'x'.repeat(500) }, JSON.parse('{"__proto__":{"a":1},"colors":{"primary":"#23AEEB"}}'), { colors: { primary: '#23AEEB' }, fonts: { heading: { name: { toString() { throw new Error('x'); } } } } },
      { colors: { primary: '#23AEEB' }, name: 'a\u202eb' }, { colors: { primary: '#23AEEB' }, attribution: { footer_text: 'a\u0000b' } }];
    for (const h of hostile) { const r = profileToStyles(h); assert.equal(typeof r, 'object'); if (r.styles) { assert.deepEqual(validateStyles(r.styles).ok, true); } else assert.ok(r.errors.length > 0); }
    assert.equal({}.a, undefined);
  });
  await ok('plain text with < > quotes is allowed as text (it is escaped by the server), and what the profile returns always passes the shared validator', () => {
    const r = profileToStyles({ ...AGENCY, name: 'A & <B> "C"', attribution: { footer_text: 'By </script>' } });
    assert.ok(r.styles && validateStyles(r.styles).ok);
  });
  console.log('the profiles folder, the choices and the files read');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-styles-'));
  const vault = path.join(tmp, 'vault'); fs.mkdirSync(vault);
  const folder = path.join(vault, '.web-obs', 'styles'); fs.mkdirSync(path.join(folder, 'clients'), { recursive: true });
  const put = (rel, obj) => fs.writeFileSync(path.join(folder, rel), typeof obj === 'string' ? obj : JSON.stringify(obj));
  put('agency.json', AGENCY);
  put('clients/examplestudio.json', { ...AGENCY, name: 'Example Studio', colors: { ...AGENCY.colors, accent_orange: '#7DD3A8', surface: '#14181F' }, attribution: { footer_text: 'Prepared by Example Studio' } });
  put('clients/broken.json', '{not json');
  put('clients/bad color.json', { colors: { primary: 'red' } });
  put('clients/notes.txt', 'ignored');
  fs.writeFileSync(path.join(folder, 'clients', 'huge.json'), JSON.stringify({ colors: { primary: '#23AEEB' }, pad: 'x'.repeat(PROFILE_MAX_BYTES + 10) }));
  await ok('the default folder is .web-obs/styles in the vault; a setting can be a full path or relative to the vault', () => {
    assert.equal(resolveStylesFolder(vault, ''), folder); assert.equal(resolveStylesFolder(vault, 'Brands/styles'), path.join(vault, 'Brands', 'styles'));
    assert.equal(resolveStylesFolder(vault, path.join(tmp, 'abs')), path.join(tmp, 'abs'));
  });
  await ok('the dialog offers Default first, then Agency, then each client file by name; files that do not pass are listed with a problem; other files are ignored', () => {
    const list = listStyleChoices(folder);
    assert.deepEqual(list.map((c) => c.id), ['default', 'agency', 'client:bad color.json', 'client:broken.json', 'client:examplestudio.json', 'client:huge.json']);
    assert.equal(list[0].label, 'Default (built-in look)'); assert.equal(list[1].label, 'Agency: Example Agency'); assert.equal(list.find((c) => c.id === 'client:examplestudio.json').label, 'Client: Example Studio');
    for (const id of ['client:bad color.json', 'client:broken.json', 'client:huge.json']) { const c = list.find((x) => x.id === id); assert.equal(c.ok, false); assert.ok(c.problem && c.problem.length > 5); }
    assert.ok(list.filter((c) => c.ok).length === 3);
  });
  await ok('an empty profiles folder offers Default and a create-it Agency entry', () => assert.deepEqual(listStyleChoices(path.join(tmp, 'nothing')).map((c) => c.id), ['default', 'agency']));
  await ok('Default without a default.json sends nothing; Agency and a client give styles with a one-line summary and the shared checks', () => {
    const d = loadStyleChoice(folder, 'default'); assert.equal(d.styles, null); assert.equal(d.problem, undefined);
    const a = loadStyleChoice(folder, 'agency'); assert.equal(a.problem, undefined); assert.equal(a.styles.accent, '#f2994a'); assert.match(a.summary, /accent #f2994a, cards #101010, fonts Oswald and Inter/); assert.ok(a.notes.some((x) => /muted #6b6b6b is adjusted/.test(x)));
    const c = loadStyleChoice(folder, 'client:examplestudio.json'); assert.equal(c.styles.accent, '#7dd3a8'); assert.equal(c.styles.name, 'Example Studio');
  });
  await ok('a default.json, when present, is used as the Default look', () => {
    put('default.json', { accent: '#445566' });
    assert.deepEqual(loadStyleChoice(folder, 'default').styles, { accent: '#445566' });
    fs.unlinkSync(path.join(folder, 'default.json'));
  });
  await ok('a choice that is not from the listing is refused: folders, dots, odd characters, other kinds, long names', () => {
    for (const id of ['client:../agency.json', 'client:..\\agency.json', 'client:a/b.json', 'client:.json', 'client:', 'client:examplestudio.JSONX', 'client:examplestudio.json\u0000', 'agency/../x', '', 'x', 'client:' + 'a'.repeat(100) + '.json', 'client:C:\\evil.json', 'default.json']) {
      const r = loadStyleChoice(folder, id); assert.equal(r.styles, null); assert.ok(r.problem, id);
    }
  });
  await ok('a missing file, a file that is not valid JSON and an oversize file give a plain problem and never throw', () => {
    assert.match(loadStyleChoice(folder, 'client:nope.json').problem, /./);
    assert.match(loadStyleChoice(folder, 'client:broken.json').problem, /not valid JSON/);
    assert.match(loadStyleChoice(folder, 'client:huge.json').problem, /larger than 64 KB/);
  });
  await ok('a link in place of a profile file is refused (no reading through links)', () => {
    const target = path.join(tmp, 'secret-looking.json'); fs.writeFileSync(target, JSON.stringify(AGENCY));
    try { fs.symlinkSync(target, path.join(folder, 'clients', 'linked.json')); } catch { return; } // links need a privilege on some systems: the check is skipped there
    assert.throws(() => readProfileFile(path.join(folder, 'clients', 'linked.json')), /not a plain file/);
    assert.match(loadStyleChoice(folder, 'client:linked.json').problem, /not a plain file/);
  });
}

// ---- the form, the draft, creating a profile file, text colors ----
{
  const F = await load('src/data/profileForm.ts');
  const S = await load('src/plugin/profileSource.ts');
  const P = await load('src/plugin/stylesProfiles.ts');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-profile-create-'));
  const form = (o = {}) => ({ ...F.EMPTY_FORM, name: 'Example Studio', accent: '#E8743B', secondary: '#4FB0C6', text: '#E6E6E6', muted: '#9A9A9A', surface: '#1B1D22', headingFont: 'Oswald', bodyFont: 'Inter', headingCase: 'uppercase', footerText: 'Prepared by Example Studio', ...o });

  const D = await load('src/data/defaultLook.ts');
  const SITE = { domain: 'example-client.com', brandName: 'Example Client', brandKit: { themeColor: '#2a7fff' } };
  const MEMBER = { name: 'Example Client', accent: '#5cff8d', secondary: '#d4f52e', surface: '#f7f7f7', text: '#323334', muted: '#707070' };
  const { suggestCardText } = await import('../src/report/styles/styles.mjs');

  await ok('a good form passes and previews', () => { const p = F.previewForm(form()); assert.ok(p.ok, JSON.stringify(p)); assert.match(p.summary, /accent #e8743b/i); });
  await ok('a form needs a name', () => assert.equal(F.formToStyles(form({ name: ' ' })).styles, null));
  for (const bad of ['red', '#12345', '#GGGGGG', 'url(x)', '#e8743b;}', 'rgb(1,2,3)', '#e8743b\u0000']) {
    await ok(`invalid color is refused: ${JSON.stringify(bad).slice(0, 24)}`, () => { const r = F.previewForm(form({ accent: bad })); assert.equal(r.ok, false); assert.ok(r.errors.length > 0); });
  }
  await ok('a font outside the bundled list is refused', () => assert.equal(F.previewForm(form({ headingFont: 'Comic Sans' })).ok, false));
  await ok('a heading case outside the list is refused', () => assert.equal(F.previewForm(form({ headingCase: 'shout' })).ok, false));
  await ok('over-long name and footer are refused', () => {
    assert.equal(F.formToStyles(form({ name: 'x'.repeat(81) })).styles, null);
    assert.equal(F.formToStyles(form({ footerText: 'y'.repeat(121) })).styles, null);
  });
  await ok('hostile text in name and footer is refused or kept as plain text, never markup in a file name or color', () => {
    const r = F.formToStyles(form({ name: '<script>alert(1)</script>', footerText: '</style><img src=x onerror=1>' }));
    if (r.styles) assert.equal(r.styles.name, '<script>alert(1)</script>'); // text only: the report server escapes it (checked in the report app)
    const file = S.profileTarget(path.join(tmp, 'h'), 'client', '<script>.example'); assert.equal(file, null);
  });
  await ok('a throwing form object never throws', () => { const evil = new Proxy({}, { get() { throw new Error('boom'); } }); assert.doesNotThrow(() => F.previewForm(evil)); assert.equal(F.formToProfile(evil), null); });
  await ok('the saved profile shape round-trips to the same styles through the plugin mapping', () => {
    const prof = F.formToProfile(form()); const back = P.profileToStyles(prof);
    assert.deepEqual(back.errors, []); const direct = F.formToStyles(form()).styles;
    for (const k of ['accent', 'secondary', 'text', 'muted', 'surface', 'headingFont', 'bodyFont', 'headingCase', 'name', 'footerText']) assert.equal(back.styles[k], direct[k], k);
    assert.deepEqual(Object.keys(prof).sort(), ['attribution', 'colors', 'fonts', 'name']);
    assert.equal(F.profileToForm(prof).accent, direct.accent);
  });
  await ok('the draft from an audit takes name, palette, theme color and a bundled font; an unknown font becomes a hint', () => {
    const d = F.draftFromManifest({ domain: 'examplestudio.example', brandName: 'Examplestudio', brandKit: { themeColor: '#ABCDEF', palette: ['#112233', { hex: '#445566' }, 'nope'], typography: { primaryFamilies: ['"Inter", sans-serif'] }, localLogoAsset: 'x.png' } }, 'client');
    assert.equal(d.form.name, 'Examplestudio'); assert.equal(d.form.accent, '#abcdef'); assert.equal(d.form.secondary, '#112233'); assert.equal(d.form.bodyFont, 'Inter'); assert.ok(d.hints.some((h) => /logo/i.test(h)));
    const e = F.draftFromManifest({ domain: 'a.example', brandKit: { typography: { primaryFamilies: ['Georgia'] } } }, 'client'); assert.equal(e.form.bodyFont, ''); assert.ok(e.hints.some((h) => /Georgia/.test(h)));
    assert.doesNotThrow(() => F.draftFromManifest(null, 'client')); assert.doesNotThrow(() => F.draftFromManifest({ brandKit: { palette: 5 } }, 'client'));
    assert.equal(F.draftFromManifest({ domain: 'h.example', brandKit: { themeColor: '#ABCDEF' } }, 'agency').form.accent, '', 'the agency form does not take the client site colours');
  });
  // ---- files ----
  const folder = path.join(tmp, 'styles');
  await ok('domain names that are not safe file stems are refused and create nothing', () => {
    for (const d of ['../evil', 'a/b.example', 'a\\b.example', '..', '.hidden.example', 'a..b.example', '', 'x'.repeat(90) + '.com', 'a b.example', 'a.example/../../x', 'CON:']) {
      assert.equal(S.safeDomain(d), null, d); assert.equal(S.createProfile(folder, 'client', d, form()).ok, false);
    }
    assert.equal(S.safeDomain('Examplestudio.Example'), 'examplestudio.example');
    assert.equal(fs.existsSync(folder), false);
  });
  await ok('Save writes clients/<domain>.json and leaves no temporary file', () => {
    const r = S.createProfile(folder, 'client', 'Examplestudio.Example', form()); assert.ok(r.ok, JSON.stringify(r));
    assert.equal(r.id, 'client:examplestudio.example.json'); assert.equal(path.relative(folder, r.file).split(path.sep).join('/'), 'clients/examplestudio.example.json');
    assert.deepEqual(fs.readdirSync(path.join(folder, 'clients')), ['examplestudio.example.json']);
    assert.equal(JSON.parse(fs.readFileSync(r.file, 'utf8')).name, 'Example Studio');
  });
  await ok('an existing file is NOT overwritten without asking; with overwrite it is replaced', () => {
    const file = path.join(folder, 'clients', 'examplestudio.example.json'); const before = fs.readFileSync(file, 'utf8');
    const r = S.createProfile(folder, 'client', 'examplestudio.example', form({ name: 'Changed' })); assert.equal(r.ok, false); assert.equal(r.code, 'exists'); assert.equal(fs.readFileSync(file, 'utf8'), before);
    const r2 = S.createProfile(folder, 'client', 'examplestudio.example', form({ name: 'Changed' }), true); assert.ok(r2.ok); assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).name, 'Changed');
  });
  await ok('replacing keeps the old file as ONE .bak copy, byte for byte, even when the old file is broken JSON', () => {
    const file = path.join(folder, 'clients', 'broken.example.json'); fs.writeFileSync(file, '{ not json');
    const r = S.createProfile(folder, 'client', 'broken.example', form(), true); assert.ok(r.ok, JSON.stringify(r));
    assert.equal(fs.readFileSync(file + '.bak', 'utf8'), '{ not json'); assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).name, 'Example Studio');
    fs.rmSync(file); fs.rmSync(file + '.bak');
  });
  await ok('replacing never writes through a .bak link (the file it points to is untouched)', () => {
    const file = path.join(folder, 'clients', 'linked-bak.example.json'); fs.writeFileSync(file, JSON.stringify({ name: 'Old' }));
    const victim = path.join(tmp, 'victim-create.txt'); fs.writeFileSync(victim, 'keep me');
    try { fs.symlinkSync(victim, file + '.bak'); } catch { fs.rmSync(file); return; }
    assert.ok(S.createProfile(folder, 'client', 'linked-bak.example', form(), true).ok);
    assert.equal(fs.readFileSync(victim, 'utf8'), 'keep me'); assert.equal(fs.lstatSync(file + '.bak').isSymbolicLink(), false); assert.equal(JSON.parse(fs.readFileSync(file + '.bak', 'utf8')).name, 'Old');
    fs.rmSync(file); fs.rmSync(file + '.bak');
  });
  await ok('an invalid form writes no file and creates no folder', () => {
    const f2 = path.join(tmp, 'styles2'); const r = S.createProfile(f2, 'agency', '', form({ accent: 'red' })); assert.equal(r.ok, false); assert.equal(r.code, 'invalid'); assert.equal(fs.existsSync(f2), false);
  });
  await ok('Agency writes agency.json (the domain plays no part)', () => {
    const f3 = path.join(tmp, 'styles3'); const r = S.createProfile(f3, 'agency', '../../x', form()); assert.ok(r.ok); assert.equal(path.basename(r.file), 'agency.json'); assert.equal(path.dirname(r.file), f3);
  });
  await ok('a link in place of the profiles folder is not followed', () => {
    const real = path.join(tmp, 'real'); fs.mkdirSync(real); const link = path.join(tmp, 'linked');
    try { fs.symlinkSync(real, link, 'junction'); } catch { return; }
    const r = S.createProfile(link, 'agency', 'x.example', form()); assert.equal(r.ok, false); assert.deepEqual(fs.readdirSync(real), []);
  });
  await ok('findProfile finds a plain file and ignores a folder with the same name', () => {
    assert.ok(S.findProfile(folder, 'client', 'examplestudio.example')); assert.equal(S.findProfile(folder, 'client', 'other.example'), null);
    fs.mkdirSync(path.join(folder, 'clients', 'dir.example.json')); assert.equal(S.findProfile(folder, 'client', 'dir.example'), null);
    assert.equal(S.createProfile(folder, 'client', 'dir.example', form(), true).ok, false, 'a folder in the way is left alone even with overwrite');
  });
  await ok('the choices always offer Agency and this site client, as "not set up yet" until the file exists', () => {
    const f4 = path.join(tmp, 'styles4'); let l = P.listStyleChoices(f4, 'new.example');
    assert.deepEqual(l.map((c) => c.id), ['default', 'agency', 'client:new.example.json']); assert.ok(l[1].missing && l[2].missing);
    assert.equal(D.resolveDefaultLook({ domain: 'new.example', choices: l, preference: 'last', lastId: 'agency' }).id, 'default', 'a missing profile is never preselected');
    assert.equal(S.createProfile(f4, 'client', 'new.example', form()).ok, true); l = P.listStyleChoices(f4, 'new.example');
    assert.ok(l.find((c) => c.id === 'client:new.example.json' && !c.missing && c.ok)); assert.equal(D.resolveDefaultLook({ domain: 'new.example', choices: l, preference: 'auto' }).id, 'client:new.example.json');
    assert.ok(!P.listStyleChoices(path.join(tmp, 'none'), undefined).some((c) => c.kind === 'client'), 'without a domain no client entry is invented');
  });
  await ok('a saved profile loads for publish through the same shared validator', () => {
    const f5 = path.join(tmp, 'styles5'); const r = S.createProfile(f5, 'client', 'h.example', form()); const l = P.loadStyleChoice(f5, r.id);
    assert.equal(l.problem, undefined); assert.equal(l.styles.accent, '#e8743b'); assert.equal(l.styles.bodyFont, 'Inter');
  });
  await ok('a very light card is refused in the form, naming the slot, and Save writes nothing', () => {
    const p = F.previewForm(form({ surface: '#ffffff' })); assert.equal(p.ok, false); assert.ok(p.errors.some((e) => /^surface:/.test(e)), p.errors.join('|'));
    const f6 = path.join(tmp, 'styles6'); const r = S.createProfile(f6, 'client', 'light.example', form({ surface: '#ffffff' })); assert.equal(r.ok, false); assert.equal(r.code, 'invalid'); assert.equal(fs.existsSync(f6), false);
  });
  await ok('a profile file with a very light card does not pass, and a dim but fixable color still does', () => {
    const f7 = path.join(tmp, 'styles7'); fs.mkdirSync(path.join(f7, 'clients'), { recursive: true });
    fs.writeFileSync(path.join(f7, 'clients', 'light.example.json'), JSON.stringify(F.formToProfile(form()) && { name: 'L', colors: { accent_orange: '#e8743b', surface: '#f5f5f5' } }));
    const l = P.loadStyleChoice(f7, 'client:light.example.json'); assert.match(l.problem ?? '', /surface:/); assert.equal(l.styles, null);
    assert.equal(F.previewForm(form({ text: '#303030' })).ok, true);
  });
  await ok('the form helpers: US spelling, plain explanations, positive wording', () => {
    assert.equal(F.usText('a colour and Colours'), 'a color and Colors');
    const texts = Object.values(F.FIELD_TEXT).map((x) => x.label + ' ' + x.help).join(' ') + F.PAGE_BACKGROUND_NOTE;
    assert.ok(!/colour|behaviour|favour|centre|grey/i.test(texts)); assert.ok(!/cannot|can't|not allowed|forbidden|error|invalid|fail/i.test(texts));
    assert.equal(F.FIELD_TEXT.footerText.label, 'Attribution footer'); assert.match(F.FIELD_TEXT.footerText.help, /below the 3D presentation layer/);
    assert.match(F.FIELD_TEXT.accent.help, /Buttons, the active step and highlights/); assert.match(F.FIELD_TEXT.secondary.help, /expandable sections/);
    assert.match(F.FIELD_TEXT.surface.help, /background of cards and panels/); assert.match(F.FIELD_TEXT.muted.help, /Small secondary text/);
    assert.match(F.PAGE_BACKGROUND_NOTE, /page background and the 3D globe never change/); assert.match(F.FIELD_TEXT.name.help, /browser tab title/);
    assert.deepEqual(F.COLOR_FIELDS, ['accent', 'secondary', 'surface']); assert.deepEqual(F.TEXT_FIELDS, ['text', 'muted', 'cardText', 'cardMuted']);
    for (const f of [...F.COLOR_FIELDS, ...F.TEXT_FIELDS]) assert.match(F.COLOR_FALLBACK[f], /^#[0-9a-f]{6}$/);
  });
  await ok('fieldIssues puts each message next to its own field, in plain words and US spelling; a clean form has none', () => {
    const ok1 = F.fieldIssues(form()); assert.equal(ok1.ok, true); assert.deepEqual(ok1.errors, {}); assert.deepEqual(ok1.general, []);
    const light = F.fieldIssues(form({ surface: '#ffffff' })); assert.equal(light.ok, false); assert.ok((light.errors.surface ?? []).some((m) => /^The page text \(#ffffff\) on the card #ffffff reaches only 1:1/.test(m) && /Set cardText/.test(m) && /Use dark text on this card/.test(m)), JSON.stringify(light.errors));
    const bad = F.fieldIssues(form({ accent: 'red' })); assert.ok((bad.errors.accent ?? []).length > 0); assert.ok(!/colour/i.test(JSON.stringify(bad)));
    assert.ok((F.fieldIssues(form({ name: ' ' })).errors.name ?? []).length > 0);
    const dim = F.fieldIssues(form({ text: '#303030' })); assert.equal(dim.ok, true); assert.ok((dim.notes.text ?? []).some((m) => /adjusted/.test(m)), JSON.stringify(dim.notes));
    assert.doesNotThrow(() => F.fieldIssues(new Proxy({}, { get() { throw new Error('boom'); } })));
  });
  await ok('with an agency profile: the client footer starts as "Prepared by <agency name>", the client name still fills Name', () => {
    const dir = path.join(tmp, 'ag-present'); fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'agency.json'), JSON.stringify({ name: 'Example Agency', colors: { accent_orange: '#e8743b' }, attribution: { footer_text: 'something else' } }));
    assert.equal(S.agencyNameFromFolder(dir), 'Example Agency');
    const d = F.draftFromManifest(SITE, 'client', S.agencyNameFromFolder(dir));
    assert.equal(d.form.footerText, 'Prepared by Example Agency'); assert.equal(d.form.name, 'Example Client');
    assert.ok(!d.hints.some((h) => /no agency profile/i.test(h)));
    assert.ok(!d.form.footerText.includes('Alpha'), 'never the client name');
    // and it survives Save: the file carries the footer, and the report would show it
    const prof = F.formToProfile({ ...d.form, accent: '#2a7fff' }); assert.equal(prof.attribution.footer_text, 'Prepared by Example Agency'); assert.equal(prof.name, 'Example Client');
  });
  await ok('without an agency profile: the footer stays empty, a hint explains how to fill it, and the client name is never used', () => {
    const dir = path.join(tmp, 'ag-absent'); fs.mkdirSync(dir, { recursive: true });
    assert.equal(S.agencyNameFromFolder(dir), null); assert.equal(S.agencyNameFromFolder(path.join(tmp, 'no-such-folder')), null);
    const d = F.draftFromManifest(SITE, 'client', S.agencyNameFromFolder(dir));
    assert.equal(d.form.footerText, ''); assert.equal(d.form.name, 'Example Client');
    assert.ok(d.hints.some((h) => /no agency profile/i.test(h) && /Look: Agency/.test(h)), d.hints.join('|'));
    assert.ok(!JSON.stringify(d.form).includes('Prepared by'), 'no invented footer in the form');
    assert.equal(F.draftFromManifest(SITE, 'client').form.footerText, '', 'no agency name given at all');
  });
  await ok('an agency file that cannot give a name counts as absent: bad JSON, no name, a number, blank, too large, a folder', () => {
    const dir = path.join(tmp, 'ag-bad'); fs.mkdirSync(dir, { recursive: true }); const w = (x) => fs.writeFileSync(path.join(dir, 'agency.json'), x);
    for (const body of ['{not json', '{"colors":{}}', '{"name":42}', '{"name":"   "}', '[]', 'null', JSON.stringify({ name: 'x', pad: 'y'.repeat(70 * 1024) })]) { w(body); assert.equal(S.agencyNameFromFolder(dir), null, body.slice(0, 20)); }
    fs.rmSync(path.join(dir, 'agency.json')); fs.mkdirSync(path.join(dir, 'agency.json')); assert.equal(S.agencyNameFromFolder(dir), null);
    fs.rmdirSync(path.join(dir, 'agency.json')); w(JSON.stringify({ name: 'n'.repeat(200) })); assert.equal(S.agencyNameFromFolder(dir).length, 80, 'long names are cut to the 80-character limit, so the footer fits its 120');
    assert.ok(F.formToStyles({ ...F.EMPTY_FORM, name: 'Client', accent: '#2a7fff', footerText: 'Prepared by ' + 'n'.repeat(80) }).styles, 'the longest generated footer is accepted');
    const hostile = F.draftFromManifest(SITE, 'client', '<script>alert(1)</script>'); assert.equal(hostile.form.footerText, 'Prepared by <script>alert(1)</script>', 'kept as plain text; the validator and the page treat it as text only');
    assert.doesNotThrow(() => F.draftFromManifest(SITE, 'client', { toString() { throw new Error('boom'); } }));
  });
  await ok('the Agency form is not prefilled with the captured site: name and footer start empty', () => {
    const d = F.draftFromManifest(SITE, 'agency', 'Example Agency'); assert.equal(d.form.name, ''); assert.equal(d.form.footerText, ''); assert.equal(d.form.accent, '');
  });
  await ok('the form has Text on the page and Text on cards (with a muted for each), with plain help for light and dark cards', () => {
    assert.equal(F.FIELD_TEXT.text.label, 'Text on the page'); assert.equal(F.FIELD_TEXT.muted.label, 'Muted on the page');
    assert.equal(F.FIELD_TEXT.cardText.label, 'Text on cards'); assert.equal(F.FIELD_TEXT.cardMuted.label, 'Muted on cards');
    assert.match(F.FIELD_TEXT.cardText.help, /dark text on a light card and light text on a dark card/); assert.match(F.FIELD_TEXT.text.help, /lightened/);
    assert.match(F.FIELD_TEXT.surface.help, /Light or dark both work/);
    const texts = Object.values(F.FIELD_TEXT).map((x) => x.label + ' ' + x.help).join(' '); assert.ok(!/colour|cannot|invalid|fail|error/i.test(texts));
  });
  await ok('the member\'s look: dark text on a light card is refused WITHOUT Text on cards (with the colors, the numbers and the way out) and passes WITH it', () => {
    const bad = F.fieldIssues({ ...F.EMPTY_FORM, ...MEMBER }); assert.equal(bad.ok, false);
    const m = (bad.errors.surface ?? []).join(' '); assert.ok(/#f7f7f7/.test(m) && /1\.07:1/.test(m) && /4\.5:1/.test(m) && /cardText/.test(m) && /dark text on this card, for example #10131a \(17\.3:1\)/.test(m), m);
    const good = F.fieldIssues({ ...F.EMPTY_FORM, ...MEMBER, cardText: '#323334' }); assert.equal(good.ok, true, JSON.stringify(good.errors));
    assert.ok((good.notes.text ?? []).some((x) => /#323334/.test(x) && /1\.57:1/.test(x) && /the page uses #[0-9a-f]{6} instead/.test(x)), 'the stage text note names the numbers and the color the page uses: ' + JSON.stringify(good.notes));
  });
  await ok('the red card (#d52924): white text on it is fine; Text on cards #323334 is refused next to its own field with both colors, 2.52:1 and a light-text suggestion', () => {
    const RED = { ...F.EMPTY_FORM, ...MEMBER, surface: '#d52924' };
    assert.equal(F.fieldIssues(RED).ok, true, 'without Text on cards the page text (white) reads on red');
    const r = F.fieldIssues({ ...RED, cardText: '#323334' }); assert.equal(r.ok, false);
    assert.ok((r.errors.cardText ?? []).some((x) => /^#323334 on the card #d52924 reaches only 2\.52:1 and needs 4\.5:1\. Use light text on this card, for example #ffffff \(5\.0:1\)\./.test(x)), JSON.stringify(r.errors));
    assert.equal(F.fieldIssues({ ...RED, cardText: '#ffffff' }).ok, true);
  });
  await ok('the one-click suggestion: the best of white and near-black for the chosen card, with its ratio', () => {
    assert.deepEqual([suggestCardText('#d52924').color, suggestCardText('#d52924').ratio.toFixed(1)], ['#ffffff', '5.0']); assert.deepEqual([suggestCardText('#f7f7f7').color, suggestCardText('#f7f7f7').ratio.toFixed(1)], ['#10131a', '17.3']);
    assert.equal(suggestCardText('#101521').color, '#ffffff'); assert.equal(suggestCardText('#777777').ok, false); assert.equal(suggestCardText('nope'), null);
    for (const hex of ['#d52924', '#f7f7f7', '#101521', '#2a7fff', '#ffcc00']) assert.equal(F.fieldIssues({ ...F.EMPTY_FORM, name: 'N', surface: hex, cardText: suggestCardText(hex).color }).ok, true, hex);
  });
  await ok('the saved profile carries Text on cards as colors.text and reads back to the same styles', () => {
    const prof = F.formToProfile({ ...F.EMPTY_FORM, ...MEMBER, cardText: '#323334', cardMuted: '#555555' });
    assert.equal(prof.colors.text, '#323334'); assert.equal(prof.colors.text_on_dark, '#323334'); assert.equal(prof.colors.muted_on_card, '#555555'); assert.equal(prof.colors.surface, '#f7f7f7');
    const back = P.profileToStyles(prof); assert.deepEqual(back.errors, []); assert.equal(back.styles.cardText, '#323334'); assert.equal(back.styles.cardMuted, '#555555'); assert.equal(back.styles.text, '#323334');
    const form2 = F.profileToForm(prof); assert.equal(form2.cardText, '#323334'); assert.equal(form2.cardMuted, '#555555');
  });
  await ok('a home profile: colors.text becomes the text on cards only when it reads on the card; colors.text_on_dark stays the page text', () => {
    const light = { name: 'Home Light', colors: { accent_orange: '#e8743b', surface: '#f7f7f7', text: '#313131', text_on_dark: '#c4c4c4' } };
    const a = P.profileToStyles(light); assert.deepEqual(a.errors, []); assert.equal(a.styles.cardText, '#313131'); assert.equal(a.styles.text, '#c4c4c4');
    const dark = { name: 'Home Dark', colors: { accent_orange: '#e8743b', surface: '#101010', text: '#313131', text_on_dark: '#c4c4c4' } };
    const d = P.profileToStyles(dark); assert.deepEqual(d.errors, []); assert.equal(d.styles.cardText, undefined, 'dark text on a dark card is left out'); assert.ok(d.notes.some((x) => /colors\.text \(#313131\) does not read on the card #101010/.test(x)), d.notes.join('|'));
    const noSurface = { name: 'No Card', colors: { accent_orange: '#e8743b', text: '#313131', text_on_dark: '#c4c4c4' } }; assert.equal(P.profileToStyles(noSurface).styles.cardText, undefined, 'the built-in dark card: dark text is left out');
    const flat = P.profileToStyles({ name: 'Flat', surface: '#f7f7f7', cardText: '#222222' }); assert.equal(flat.styles.cardText, '#222222', 'a flat styles file passes through');
  });
}

// ---- editing a saved profile and the default look ----
{
  const F = await load('src/data/profileForm.ts');
  const S = await load('src/plugin/profileSource.ts');
  const P = await load('src/plugin/stylesProfiles.ts');
  const D = await load('src/data/defaultLook.ts');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-profile-edit-'));
  const read = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));
  const mk = (name) => { const d = path.join(tmp, name); fs.mkdirSync(path.join(d, 'clients'), { recursive: true }); return d; };

  const HOME = { name: 'Example Agency', voice_context: 'agency', voice: ['Be positive.'], logo: '(a path)', notes: { private: 'keep me', n: [1, 2, 3] },
    colors: { primary: '#23AEEB', accent_orange: '#F2994A', blue_light: '#2ECDF5', text_on_dark: '#C4C4C4', muted: '#6B6B6B', surface: '#101010', grey_1: '#1C1F26', tint: '#EAF6FC', text: '#313131' },
    fonts: { heading: { name: 'Oswald', case: 'uppercase', file: 'Oswald.ttf' }, body: { name: 'Inter' } }, attribution: { header_text: 'Example Agency', footer_text: 'Prepared by Example Agency' } };


  console.log('edit: the saved file opens in the form and saves back in place');
  await ok('every field of a saved profile is in the form (text on cards included); a dark colors.text on a dark card is left out, not shown as an error', () => {
    const d = mk('open'); fs.writeFileSync(path.join(d, 'agency.json'), JSON.stringify(HOME));
    const r = S.readProfileForEdit(d, 'agency'); assert.ok(r.ok, JSON.stringify(r)); assert.equal(r.shape, 'home');
    assert.equal(r.form.name, 'Example Agency'); assert.equal(r.form.accent, '#F2994A'); assert.equal(r.form.secondary, '#2ECDF5'); assert.equal(r.form.text, '#C4C4C4'); assert.equal(r.form.muted, '#6B6B6B'); assert.equal(r.form.surface, '#101010');
    assert.equal(r.form.cardText, '', 'colors.text #313131 does not read on the dark card #101010'); assert.equal(r.form.headingFont, 'Oswald'); assert.equal(r.form.headingCase, 'uppercase'); assert.equal(r.form.bodyFont, 'Inter'); assert.equal(r.form.footerText, 'Prepared by Example Agency');
    assert.equal(F.fieldIssues(r.form).ok, true);
    const light = { name: 'Example Client', colors: { accent_orange: '#e8743b', surface: '#f7f7f7', text: '#222222', muted_on_card: '#555555', text_on_dark: '#e6e6e6' } };
    fs.writeFileSync(path.join(d, 'clients', 'example-client.com.json'), JSON.stringify(light));
    const c = S.readProfileForEdit(d, 'client:example-client.com.json'); assert.equal(c.form.cardText, '#222222'); assert.equal(c.form.cardMuted, '#555555');
  });
  await ok('a changed field is saved in place; every unknown key stays exactly as it was; the old file is kept as ONE backup; no other file appears', () => {
    const d = mk('save'); const file = path.join(d, 'agency.json'); fs.writeFileSync(file, JSON.stringify(HOME, null, 2));
    const before = fs.readFileSync(file, 'utf8'); const r = S.readProfileForEdit(d, 'agency');
    const res = S.updateProfile(d, 'agency', r.form, { ...r.form, accent: '#E8743B', footerText: 'Prepared by Example Studio', cardText: '#ffffff' }, r.baseHash); assert.ok(res.ok, JSON.stringify(res));
    const now = read(file);
    assert.equal(now.colors.accent_orange, '#E8743B'); assert.equal(now.colors.primary, '#23AEEB', 'the link color is not touched'); assert.equal(now.attribution.footer_text, 'Prepared by Example Studio'); assert.equal(now.colors.text, '#ffffff');
    assert.deepEqual(now.notes, HOME.notes); assert.deepEqual(now.voice, HOME.voice); assert.equal(now.logo, HOME.logo); assert.equal(now.colors.grey_1, '#1C1F26'); assert.equal(now.fonts.heading.file, 'Oswald.ttf'); assert.equal(now.attribution.header_text, 'Example Agency');
    assert.equal(fs.readFileSync(res.backup, 'utf8'), before, 'the backup is the file as it was'); assert.equal(res.backup, file + '.bak');
    assert.deepEqual(fs.readdirSync(d).sort(), ['agency.json', 'agency.json.bak', 'clients'], 'no temporary or other file is left');
    const r2 = S.readProfileForEdit(d, 'agency'); const res2 = S.updateProfile(d, 'agency', r2.form, { ...r2.form, secondary: '#4fb0c6' }, r2.baseHash); assert.ok(res2.ok);
    assert.equal(read(file + '.bak').colors.accent_orange, '#E8743B', 'the backup is replaced by the previous version: one backup copy, not a growing list'); assert.deepEqual(fs.readdirSync(d).sort(), ['agency.json', 'agency.json.bak', 'clients']);
  });
  await ok('a field the person did not touch is not rewritten (an odd stored value stays as it was), and clearing a field removes its key', () => {
    const d = mk('clear'); const odd = { name: 'Odd', colors: { accent_orange: '#F2994A', surface: '#101010', text_on_dark: '#C4C4C4', blue_light: '#2ECDF5', weird: 5 }, extra: [1] };
    const file = path.join(d, 'agency.json'); fs.writeFileSync(file, JSON.stringify(odd));
    const r = S.readProfileForEdit(d, 'agency'); S.updateProfile(d, 'agency', r.form, { ...r.form, secondary: '' }, r.baseHash);
    const now = read(file); assert.equal(now.colors.blue_light, undefined); assert.equal(now.colors.weird, 5); assert.deepEqual(now.extra, [1]); assert.equal(now.colors.accent_orange, '#F2994A');
  });
  await ok('a flat styles file is edited in its own shape', () => {
    const d = mk('flat'); const file = path.join(d, 'clients', 'flat.test.json'); fs.writeFileSync(file, JSON.stringify({ name: 'Flat', accent: '#2a7fff', surface: '#101010', cardText: '#eeeeee', keepMe: true }));
    const r = S.readProfileForEdit(d, 'client:flat.test.json'); assert.equal(r.shape, 'flat'); assert.equal(r.form.cardText, '#eeeeee');
    S.updateProfile(d, 'client:flat.test.json', r.form, { ...r.form, accent: '#e8743b', cardText: '' }, r.baseHash); const now = read(file);
    assert.equal(now.accent, '#e8743b'); assert.equal(now.cardText, undefined); assert.equal(now.keepMe, true); assert.equal(now.colors, undefined);
  });
  await ok('saving never writes through a .bak link, and a folder at that name is refused (nothing is written)', () => {
    const d = mk('bak-link'); const file = path.join(d, 'agency.json'); fs.writeFileSync(file, JSON.stringify(HOME));
    const victim = path.join(tmp, 'victim-edit.txt'); fs.writeFileSync(victim, 'keep me');
    try { fs.symlinkSync(victim, file + '.bak'); } catch { return; }
    const r = S.readProfileForEdit(d, 'agency'); const res = S.updateProfile(d, 'agency', r.form, { ...r.form, name: 'Linked' }, r.baseHash); assert.ok(res.ok, JSON.stringify(res));
    assert.equal(fs.readFileSync(victim, 'utf8'), 'keep me'); assert.equal(fs.lstatSync(file + '.bak').isSymbolicLink(), false); assert.equal(read(file + '.bak').name, HOME.name);
    const d2 = mk('bak-folder'); const f2 = path.join(d2, 'agency.json'); fs.writeFileSync(f2, JSON.stringify(HOME)); fs.mkdirSync(f2 + '.bak'); const before = fs.readFileSync(f2, 'utf8');
    const r2 = S.readProfileForEdit(d2, 'agency'); assert.equal(S.updateProfile(d2, 'agency', r2.form, { ...r2.form, name: 'X' }, r2.baseHash).ok, false); assert.equal(fs.readFileSync(f2, 'utf8'), before);
  });
  await ok('a clients folder that is a link is not edited through', () => {
    const d = path.join(tmp, 'clients-link'); fs.mkdirSync(d); const outside = path.join(tmp, 'outside-clients'); fs.mkdirSync(outside);
    const file = path.join(outside, 'x.example.json'); fs.writeFileSync(file, JSON.stringify({ name: 'Outside', colors: { accent_orange: '#e8743b' } })); const before = fs.readFileSync(file, 'utf8');
    try { fs.symlinkSync(outside, path.join(d, 'clients'), 'junction'); } catch { return; }
    const r = S.readProfileForEdit(d, 'client:x.example.json'); const res = r.ok ? S.updateProfile(d, 'client:x.example.json', r.form, { ...r.form, name: 'Changed' }, r.baseHash) : r;
    assert.equal(res.ok, false); assert.equal(fs.readFileSync(file, 'utf8'), before);
  });
  await ok('a form that does not pass is never written (the file and the backup stay as they were)', () => {
    const d = mk('invalid'); const file = path.join(d, 'agency.json'); fs.writeFileSync(file, JSON.stringify(HOME)); const before = fs.readFileSync(file, 'utf8'); const r = S.readProfileForEdit(d, 'agency');
    for (const bad of [{ accent: 'red' }, { surface: '#ffffff' }, { name: '' }, { cardText: '#101010' }, { headingFont: 'Comic Sans' }]) { const res = S.updateProfile(d, 'agency', r.form, { ...r.form, ...bad }, r.baseHash); assert.equal(res.ok, false, JSON.stringify(bad)); assert.equal(res.code, 'invalid'); }
    assert.equal(fs.readFileSync(file, 'utf8'), before); assert.deepEqual(fs.readdirSync(d).sort(), ['agency.json', 'clients']);
  });
  await ok('if the file changed since it was opened nothing is written', () => {
    const d = mk('changed'); const file = path.join(d, 'agency.json'); fs.writeFileSync(file, JSON.stringify(HOME)); const r = S.readProfileForEdit(d, 'agency');
    fs.writeFileSync(file, JSON.stringify({ ...HOME, name: 'Changed Meanwhile' })); const res = S.updateProfile(d, 'agency', r.form, { ...r.form, accent: '#e8743b' }, r.baseHash);
    assert.equal(res.ok, false); assert.equal(res.code, 'changed'); assert.equal(read(file).name, 'Changed Meanwhile'); assert.deepEqual(fs.readdirSync(d).sort(), ['agency.json', 'clients']);
  });
  await ok('hand-edited and older files load safely: bad JSON, wrong types, lists, huge files, links, odd names, unknown and hostile keys never crash or run', () => {
    const d = mk('hand'); const w = (n, body) => fs.writeFileSync(path.join(d, 'clients', n), body);
    w('badjson.test.json', '{not json'); w('list.test.json', '[1,2]'); w('null.test.json', 'null'); w('types.test.json', JSON.stringify({ name: 5, colors: { surface: ['#000000'], accent_orange: {}, text_on_dark: 7 }, fonts: 'x', attribution: 4 }));
    w('huge.test.json', JSON.stringify({ name: 'h', pad: 'x'.repeat(70 * 1024) })); w('proto.test.json', '{"__proto__":{"polluted":1},"constructor":{"prototype":{"polluted":2}},"name":"P","colors":{"__proto__":{"x":1}}}');
    for (const n of ['badjson', 'list', 'null', 'huge']) { const r = S.readProfileForEdit(d, `client:${n}.test.json`); assert.equal(r.ok, false, n); assert.ok(r.message.length > 10); }
    const t = S.readProfileForEdit(d, 'client:types.test.json'); assert.ok(t.ok); assert.equal(t.form.name, ''); assert.equal(t.form.surface, ''); assert.equal(t.form.accent, '');
    const pr = S.readProfileForEdit(d, 'client:proto.test.json'); assert.ok(pr.ok); assert.equal(pr.form.name, 'P'); assert.equal(({}).polluted, undefined);
    const saved = S.updateProfile(d, 'client:proto.test.json', pr.form, { ...pr.form, accent: '#2a7fff' }, pr.baseHash); assert.ok(saved.ok); assert.equal(({}).polluted, undefined); assert.equal(Object.prototype.hasOwnProperty.call(read(path.join(d, 'clients', 'proto.test.json')), 'polluted'), false);
    assert.equal(S.readProfileForEdit(d, 'client:missing.test.json').ok, false); for (const bad of ['default', 'client:../x.json', 'client:a/b.json', 'client:', 'nope', '', null]) assert.equal(S.readProfileForEdit(d, bad).ok, false, String(bad));
    const real = path.join(tmp, 'realdir'); fs.mkdirSync(real); fs.mkdirSync(path.join(d, 'clients', 'dir.test.json')); assert.equal(S.readProfileForEdit(d, 'client:dir.test.json').ok, false);
    try { fs.symlinkSync(path.join(real), path.join(d, 'clients', 'link.test.json'), 'junction'); assert.equal(S.readProfileForEdit(d, 'client:link.test.json').ok, false); } catch { /* links not allowed here */ }
  });
  await ok('the form helpers never throw on hostile stored values', () => {
    for (const raw of [null, undefined, 5, 'x', [], { colors: null }, { colors: [] }, { fonts: { heading: 5 } }, { name: { toString() { throw new Error('boom'); } } }]) { assert.doesNotThrow(() => F.profileToForm(raw)); assert.doesNotThrow(() => F.applyFormToRaw(raw, F.EMPTY_FORM, { ...F.EMPTY_FORM, name: 'N', accent: '#112233' })); }
    const out = F.applyFormToRaw({ colors: 5, fonts: 7 }, F.EMPTY_FORM, { ...F.EMPTY_FORM, surface: '#101010', headingFont: 'Oswald' }); assert.equal(typeof out, 'object');
  });
  console.log('the profiles list (settings)');
  await ok('the list shows Agency and every client with a one-line summary, and the problem the validator finds; backups and odd files are not listed', () => {
    const d = mk('list'); fs.writeFileSync(path.join(d, 'agency.json'), JSON.stringify(HOME)); const w = (nm, o) => fs.writeFileSync(path.join(d, 'clients', nm), typeof o === 'string' ? o : JSON.stringify(o));
    w('example-client.com.json', { name: 'Example Client', colors: { accent_orange: '#e8743b', surface: '#f7f7f7', text: '#222222' }, fonts: { heading: { name: 'Oswald' } } }); w('broken.test.json', '{nope'); w('light.test.json', { name: 'Light', colors: { accent_orange: '#e8743b', surface: '#ffffff' } }); w('example-client.com.json.bak', '{}'); w('notes.txt', 'x');
    const l = P.listProfileSummaries(d); assert.deepEqual(l.map((x) => x.id), ['agency', 'client:broken.test.json', 'client:example-client.com.json', 'client:light.test.json']);
    const by = Object.fromEntries(l.map((x) => [x.id, x])); assert.match(by.agency.summary, /accent #f2994a/); assert.match(by.agency.summary, /cards #101010/); assert.match(by.agency.summary, /Oswald/); assert.equal(by.agency.problem, undefined);
    assert.match(by['client:example-client.com.json'].summary, /cards #f7f7f7/); assert.equal(by['client:example-client.com.json'].problem, undefined);
    assert.ok(by['client:broken.test.json'].problem && /not valid JSON/.test(by['client:broken.test.json'].problem)); assert.ok(by['client:light.test.json'].problem && /surface/.test(by['client:light.test.json'].problem));
    assert.deepEqual(P.listProfileSummaries(path.join(tmp, 'nothing')), []);
  });
  console.log('the default look');
  const ch = (...ids) => ids.map((id) => ({ id, ...(id.endsWith('*') ? { id: id.slice(0, -1), missing: true } : {}) }));
  const CHOICES = (client, agency) => [{ id: 'default' }, agency ? { id: 'agency' } : { id: 'agency', missing: true }, client ? { id: 'client:example-client.com.json' } : { id: 'client:example-client.com.json', missing: true }, { id: 'client:other.test.json' }];
  await ok('auto: the client profile for this site, else the Agency profile, else Default (all four cases)', () => {
    const r = (c, a) => D.resolveDefaultLook({ domain: 'example-client.com', choices: CHOICES(c, a), preference: 'auto' });
    assert.equal(r(true, true).id, 'client:example-client.com.json'); assert.equal(r(true, false).id, 'client:example-client.com.json'); assert.equal(r(false, true).id, 'agency'); assert.equal(r(false, false).id, 'default');
    for (const x of [r(true, true), r(false, true), r(false, false)]) assert.ok(x.reason.length > 20);
    assert.match(r(false, true).reason, /no client profile for this site, so the Agency profile is used/);
  });
  await ok('the preference options and their precedence', () => {
    const r = (pref, c, a, lastId) => D.resolveDefaultLook({ domain: 'example-client.com', choices: CHOICES(c, a), preference: pref, lastId });
    assert.equal(r('agency', true, true).id, 'agency', 'agency wins over the client file'); assert.equal(r('agency', true, false).id, 'default'); assert.match(r('agency', true, false).reason, /none yet/);
    assert.equal(r('default', true, true).id, 'default');
    assert.equal(r('last', true, true, 'client:other.test.json').id, 'client:other.test.json'); assert.equal(r('last', true, true, 'agency').id, 'agency'); assert.equal(r('last', true, true, 'default').id, 'default');
    assert.equal(r('last', true, true, 'client:gone.test.json').id, 'client:example-client.com.json', 'a last choice that no longer exists falls back to auto'); assert.equal(r('last', false, true, undefined).id, 'agency');
    assert.equal(r('last', true, true, 'client:example-client.com.json').id, 'client:example-client.com.json');
  });
  await ok('a look that is "not set up yet" is never preselected; a missing or unknown preference means auto; case in the domain does not matter; hostile input never throws', () => {
    assert.equal(D.resolveDefaultLook({ domain: 'example-client.com', choices: CHOICES(false, false), preference: 'agency', lastId: 'agency' }).id, 'default');
    assert.equal(D.resolveDefaultLook({ domain: 'Example-Client.COM', choices: CHOICES(true, false), preference: 'banana' }).id, 'client:example-client.com.json'); assert.equal(D.resolveDefaultLook({ domain: 'example-client.com', choices: CHOICES(false, true) }).id, 'agency');
    for (const bad of [null, undefined, {}, { domain: 5, choices: 7 }, { domain: 'x', choices: [null] }]) assert.doesNotThrow(() => D.resolveDefaultLook(bad)); assert.equal(D.resolveDefaultLook(null).id, 'default');
    assert.deepEqual(D.DEFAULT_LOOK_PREFERENCES.map((p) => p.id), ['auto', 'agency', 'default', 'last']); assert.match(D.DEFAULT_LOOK_PREFERENCES[0].label, /recommended/);
  });
  await ok('the seam: profileSource.ts exports the decision and the edit functions beside findProfile and createProfile', () => {
    for (const k of ['findProfile', 'createProfile', 'resolveDefaultLook', 'readProfileForEdit', 'updateProfile']) assert.equal(typeof S[k], 'function', k);
  });
}

fs.rmSync(path.join(os.tmpdir(), 'wo-never-created'), { recursive: true, force: true });
console.log(`Style profiles OK: ${n} checks passed.`);
