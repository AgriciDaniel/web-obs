// The engine is packed into main.js so a community install (main.js, manifest.json, styles.css only) still works.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { build } from 'esbuild';
import { engineFileHashes } from './engine-files.mjs';

const out = await build({ entryPoints: ['src/plugin/engineBundle.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent', external: ['node:*'] });
const { installEngine, decodeEngineBundle } = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].contents).toString('base64'));

let passed = 0;
const check = (name, fn) => { fn(); passed += 1; console.log('[PASS]', name); };
const temp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'web-obs-bundle-'));
const pack = (files) => zlib.gzipSync(Buffer.from(JSON.stringify({ schemaVersion: 1, files }))).toString('base64');

const source = engineFileHashes('engine');
const real = pack(Object.fromEntries(Object.keys(source).map((f) => [f, fs.readFileSync(path.join('engine', f)).toString('base64')])));

check('a plugin folder with only main.js gets the full engine', () => {
  const dir = temp();
  const result = installEngine(dir, real);
  assert.equal(result.state, 'installed');
  assert.deepEqual(engineFileHashes(path.join(dir, 'engine')), source);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, 'engine-manifest.json'), 'utf8')).files, source);
});

check('a second start writes nothing', () => {
  const dir = temp();
  installEngine(dir, real);
  const again = installEngine(dir, real);
  assert.equal(again.state, 'ok');
  assert.deepEqual(again.written, []);
});

check('an edited file is repaired and a deleted file is restored', () => {
  const dir = temp();
  installEngine(dir, real);
  fs.writeFileSync(path.join(dir, 'engine', 'sitemap.py'), '# tampered\n');
  fs.rmSync(path.join(dir, 'engine', 'pipeline.py'));
  const result = installEngine(dir, real);
  assert.equal(result.state, 'repaired');
  assert.deepEqual(result.written.sort(), ['pipeline.py', 'sitemap.py']);
  assert.deepEqual(engineFileHashes(path.join(dir, 'engine')), source);
});

check('extra files in the engine folder are left alone', () => {
  const dir = temp();
  installEngine(dir, real);
  fs.mkdirSync(path.join(dir, 'engine', '.venv'));
  fs.writeFileSync(path.join(dir, 'engine', '.venv', 'keep.txt'), 'mine');
  installEngine(dir, real);
  assert.equal(fs.readFileSync(path.join(dir, 'engine', '.venv', 'keep.txt'), 'utf8'), 'mine');
});

check('a file dropped by a newer release is removed, but an edited or unrelated one is kept', () => {
  const dir = temp();
  const body = (text) => Buffer.from(text).toString('base64');
  installEngine(dir, pack({ 'keep.py': body('k'), 'old_name.py': body('old'), 'edited_old.py': body('e') }));
  fs.writeFileSync(path.join(dir, 'engine', 'edited_old.py'), 'user edit');
  fs.writeFileSync(path.join(dir, 'engine', 'mine.txt'), 'mine');
  const result = installEngine(dir, pack({ 'keep.py': body('k') }));
  assert.equal(fs.existsSync(path.join(dir, 'engine', 'old_name.py')), false);
  assert.equal(fs.readFileSync(path.join(dir, 'engine', 'edited_old.py'), 'utf8'), 'user edit');
  assert.equal(fs.readFileSync(path.join(dir, 'engine', 'mine.txt'), 'utf8'), 'mine');
  assert.ok(result.written.includes('-old_name.py'));
});

check('a bundle cannot write outside the engine folder', () => {
  for (const bad of ['../evil.py', '/etc/evil.py', 'a/../../evil.py', 'a\\b.py']) {
    const dir = temp();
    assert.throws(() => installEngine(dir, pack({ [bad]: Buffer.from('x').toString('base64') })), /outside the engine folder/);
    assert.equal(fs.existsSync(path.join(dir, '..', 'evil.py')), false);
  }
});

check('a missing bundle is reported, not fatal', () => {
  assert.equal(installEngine(temp(), undefined).state, 'unavailable');
  assert.throws(() => decodeEngineBundle(zlib.gzipSync(Buffer.from('{"schemaVersion":2}')).toString('base64')), /Unrecognized/);
});

check('the built main.js carries the current engine', () => {
  if (!fs.existsSync('dist-plugin/main.js')) {
    execFileSync(process.execPath, ['esbuild.config.mjs'], { stdio: 'ignore' });
  }
  const main = fs.readFileSync('dist-plugin/main.js', 'utf8');
  const match = /__WEB_OBS_ENGINE_BUNDLE__|"H4sI[A-Za-z0-9+/=]{1000,}"/.exec(main);
  assert.ok(match, 'main.js does not contain a packed engine');
  const encoded = /"(H4sI[A-Za-z0-9+/=]{1000,})"/.exec(main)[1];
  const bundle = decodeEngineBundle(encoded);
  const dir = temp();
  installEngine(dir, encoded);
  assert.deepEqual(engineFileHashes(path.join(dir, 'engine')), source, 'packed engine is stale, rebuild the plugin');
  assert.equal(Object.keys(bundle.files).length, Object.keys(source).length);
});

console.log(`Engine bundle: ${passed} cases passed.`);
