#!/usr/bin/env node
// Unit checks for the diagnostics report. Compiles the pure TS module with esbuild in memory.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';

const out = await build({ entryPoints: ['src/plugin/doctorReport.ts'], bundle: true, format: 'esm', write: false, platform: 'node' });
const mod = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64'));

const good = {
  desktopVault: true, pluginVersion: '0.1.1', engineFound: true, engineVersion: '0.1.1', engineMismatches: [],
  pythonBin: '/x/python3', pythonVersion: '3.14.2', missingCore: [], renderMode: 'auto',
  playwrightAvailable: true, chromiumAvailable: true, browserError: null, vaultWritable: true,
  network: { ok: true, detail: 'Outbound HTTPS works.' },
};
const states = (facts) => Object.fromEntries(mod.buildDoctorReport(facts).map((r) => [r.id, r.state]));

let rows = mod.buildDoctorReport(good);
assert.ok(rows.every((r) => r.state === 'pass'), 'healthy setup is all pass');
assert.equal(mod.summarizeDoctor(rows).state, 'pass');
assert.ok(rows.filter((r) => r.state !== 'pass').every((r) => !r.fix));

assert.equal(states({ ...good, pythonVersion: '3.12.4' }).python, 'fail');
assert.equal(states({ ...good, pythonVersion: null }).python, 'fail');
assert.equal(states({ ...good, pythonVersion: '3.14.0' }).python, 'pass');
assert.equal(states({ ...good, pythonVersion: '4.0.0' }).python, 'pass');
assert.deepEqual(mod.buildDoctorReport({ ...good, missingCore: ['lxml', 'bs4'] }).find((r) => r.id === 'packages').detail, 'Missing: lxml, bs4.');
assert.equal(states({ ...good, missingCore: null }).packages, 'fail');

// Browser: only a hard failure when rendering is forced.
assert.equal(states({ ...good, playwrightAvailable: false }).browser, 'warn');
assert.equal(states({ ...good, playwrightAvailable: false, renderMode: 'always' }).browser, 'fail');
assert.equal(states({ ...good, chromiumAvailable: false }).browser, 'warn');
assert.equal(states({ ...good, playwrightAvailable: false, renderMode: 'never' }).browser, 'pass');

// Engine integrity.
assert.equal(states({ ...good, engineFound: false }).engine, 'fail');
assert.equal(states({ ...good, engineMismatches: ['extractor.py'] }).engine, 'fail');
assert.equal(states({ ...good, engineMismatches: null }).engine, 'warn');
assert.match(mod.buildDoctorReport({ ...good, engineMismatches: ['a', 'b', 'c', 'd', 'e', 'f'] }).find((r) => r.id === 'engine').detail, /and 2 more/);
assert.equal(states({ ...good, engineVersion: '0.0.9' }).version, 'warn');

// Environment.
assert.equal(states({ ...good, desktopVault: false }).vault, 'fail');
assert.equal(states({ ...good, vaultWritable: false }).write, 'fail');
assert.equal(states({ ...good, vaultWritable: null }).write, 'warn');
assert.equal(states({ ...good, network: { ok: false, detail: 'down' } }).network, 'warn');

// Summary and text report.
const bad = mod.buildDoctorReport({ ...good, pythonVersion: null, network: { ok: false, detail: 'down' } });
const summary = mod.summarizeDoctor(bad);
assert.equal(summary.state, 'fail');
assert.equal(summary.failures, 1);
assert.equal(summary.warnings, 1);
assert.match(mod.doctorReportText(bad), /FAIL {2}Python/);
assert.equal(mod.summarizeDoctor(mod.buildDoctorReport({ ...good, network: null })).state, 'warn');
assert.deepEqual(mod.parsePythonVersion('Python 3.14.1'), { major: 3, minor: 14 });
assert.equal(mod.parsePythonVersion('nope'), null);

// Optional packages are informational: missing ones never warn or fail.
const someOptional = mod.buildDoctorReport({ ...good, optionalPackages: { dnspython: false, pyspellchecker: true, html5lib: false } });
const optionalRow = someOptional.find((r) => r.id === 'optional');
assert.equal(optionalRow.state, 'pass');
assert.match(optionalRow.detail, /Optional, not installed: dnspython \(email DNS checks\), html5lib/);
assert.equal(mod.summarizeDoctor(someOptional).state, 'pass');
assert.match(mod.buildDoctorReport({ ...good, optionalPackages: { dnspython: true, pyspellchecker: true, html5lib: true } }).find((r) => r.id === 'optional').detail, /are available/);
assert.equal(mod.buildDoctorReport({ ...good, optionalPackages: {} }).find((r) => r.id === 'optional').state, 'pass');
assert.ok(!mod.buildDoctorReport(good).some((r) => r.id === 'optional'), 'older probes without optional data add no row');

// Every row with a problem tells the user what to do next.
for (const facts of [{ ...good, pythonVersion: null }, { ...good, missingCore: ['lxml'] }, { ...good, vaultWritable: false }, { ...good, engineFound: false }]) {
  for (const r of mod.buildDoctorReport(facts).filter((r) => r.state === 'fail')) assert.ok(r.fix, `fail row ${r.id} has a fix`);
}

// The doctor must stay read-only: no installs, no network calls beyond one HEAD, no shell.
const src = fs.readFileSync('src/plugin/doctor.ts', 'utf8');
assert.ok(!/child_process|pip install|npm install/.test(src), 'doctor never installs or shells out');

// Friendly engine errors.
const errOut = await build({ entryPoints: ['src/plugin/crawlErrors.ts'], bundle: true, format: 'esm', write: false, platform: 'node' });
const errs = await import('data:text/javascript;base64,' + Buffer.from(errOut.outputFiles[0].text).toString('base64'));
assert.match(errs.friendlyEngineError("Traceback (most recent call last):\n  File \"x.py\", line 1\nModuleNotFoundError: No module named 'lxml.etree'"), /missing "lxml"/);
assert.match(errs.friendlyEngineError('PermissionError: [Errno 13] Permission denied: /vault/sites'), /could not write to the vault/);
assert.match(errs.friendlyEngineError('OSError: [Errno 28] No space left on device'), /disk is full/);
assert.match(errs.friendlyEngineError('Traceback (most recent call last):\n  File "a"\nValueError: bad thing happened'), /unexpected error: ValueError: bad thing happened/);
assert.ok(!/Traceback/.test(errs.friendlyEngineError('Traceback (most recent call last):\n  File "a"\nKeyError: 1')));
assert.match(errs.friendlyEngineError('', 'Crawler exited with code 1.'), /Crawler exited with code 1\..*diagnostics/);
assert.equal(errs.friendlyEngineError('Plain readable message from the crawler.'), 'Plain readable message from the crawler.');
assert.match(errs.friendlySpawnError('/bad/python', 'spawn /bad/python ENOENT'), /Python was not found at "\/bad\/python"/);
assert.match(errs.friendlySpawnError('p', 'EACCES'), /not executable/);
console.log('[PASS] Diagnostics report verified.');
