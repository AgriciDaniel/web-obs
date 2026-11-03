import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}

const { parseSiteManifest } = await load('src/data/validateManifest.ts');
const { PREVIEW_SITE_MANIFEST: fixture } = await load('src/data/demoSite.ts');
const resourceText = ['mimeType', 'checkStatus', 'downloadState', 'localPath', 'error', 'downloadReason', 'sha256', 'sourceSha256', 'localFileStatus', 'proposedLocalPath'];
const referenceText = ['label', 'language'];
const resource = () => ({ id: 'resource-fixture', url: 'https://fixture.invalid/image.png', type: 'image', references: [{ pageUrl: fixture.nodes[0].url, role: 'image' }] });
const capture = (entry = resource()) => ({ ...structuredClone(fixture), resources: [entry] });
let count = 0;
function check(name, fn) { fn(); count++; console.log('[PASS] ' + name); }

check('legacy captures may omit resources and resource optional fields', () => {
  const manifest = structuredClone(fixture);
  delete manifest.resources;
  assert.equal(parseSiteManifest(manifest), manifest);
  const withResource = capture();
  assert.equal(parseSiteManifest(withResource), withResource);
});

check('optional resource and reference text preserves strings, nulls, and absent values', () => {
  for (const value of ['', 'Fixture text', null, undefined]) {
    const entry = resource();
    for (const key of resourceText) entry[key] = value;
    for (const key of referenceText) entry.references[0][key] = value;
    entry.statusCode = null;
    const manifest = capture(entry);
    const before = JSON.stringify(manifest);
    assert.equal(parseSiteManifest(manifest), manifest);
    assert.equal(JSON.stringify(manifest), before, 'Validation must not alter captured data');
  }
});

check('malformed optional resource text and reference text is rejected before React', () => {
  for (const value of [{ unexpected: 'object' }, [], ['image'], 1, true]) {
    for (const key of resourceText) {
      const entry = resource();
      entry[key] = value;
      assert.throws(() => parseSiteManifest(capture(entry)), /Invalid site capture: invalid resource text fields/, key);
    }
    for (const key of referenceText) {
      const entry = resource();
      entry.references[0][key] = value;
      assert.throws(() => parseSiteManifest(capture(entry)), /Invalid site capture: invalid resource references/, key);
    }
  }
});

check('required resource fields reject coercible types and malformed references', () => {
  for (const key of ['id', 'url', 'type']) {
    for (const value of [null, {}, ['image'], 1, true, undefined]) {
      const entry = resource();
      entry[key] = value;
      assert.throws(() => parseSiteManifest(capture(entry)), /Invalid site capture: invalid resource inventory/, key);
    }
  }
  for (const key of ['pageUrl', 'role']) {
    for (const value of [null, {}, [], 1, true, undefined]) {
      const entry = resource();
      entry.references[0][key] = value;
      assert.throws(() => parseSiteManifest(capture(entry)), /Invalid site capture: invalid resource references/, key);
    }
  }
  for (const value of [null, {}, [null], [[]]]) {
    const entry = resource();
    entry.references = value;
    assert.throws(() => parseSiteManifest(capture(entry)), /Invalid site capture: invalid resource references/);
  }
});

check('resource metrics reject nonnumeric, negative, and nonfinite values', () => {
  for (const key of ['statusCode', 'bytes']) {
    for (const value of [{}, [], '200', true, -1, NaN, Infinity]) {
      const entry = resource();
      entry[key] = value;
      assert.throws(() => parseSiteManifest(capture(entry)), /Invalid site capture: invalid resource metrics/, key);
    }
    for (const value of [0, 200]) {
      const entry = resource();
      entry[key] = value;
      assert.doesNotThrow(() => parseSiteManifest(capture(entry)));
    }
  }
});

function evidenceCapture() {
  const manifest = capture();
  manifest.captureProvenance = {
    engineSha256: 'a'.repeat(64), configuration: { renderMode: 'never', imageMode: 'all' },
    engineFiles: { 'crawl_site.py': 'b'.repeat(64) },
    runtime: { pythonVersion: '3.14.0', platform: 'linux', pythonExecutable: '/synthetic/python', packages: { requests: '2.32.0', playwright: null } },
    browserEvidence: 'Per-page renderUsed records rendering.',
  };
  manifest.siteIntel = {
    ...manifest.siteIntel,
    techStack: {
      analyticsAndPixels: [], measurementIds: { ga4: [], gtm: [], googleAds: [] },
      cmsOrFramework: [], hostingAndCdn: [], securityHeaders: { present: [], missing: [] },
      coverage: { sampledPages: 1, capturedHtmlPages: 2, sourceUrls: [fixture.origin], selection: 'Home first', securityHeadersScope: 'Home response' },
    },
  };
  manifest.linkHealth = {
    totalCount: 0, checkedCount: 0, uncheckedCount: 0, unknownCount: 0, assessedCount: 0,
    coverageComplete: true, results: [], brokenLinks: [], serverErrors: [], unknownLinks: [],
    updatedAt: '2026-11-02T00:00:00Z',
  };
  return manifest;
}

check('new evidence fields validate without mutation and legacy captures may omit them', () => {
  const manifest = evidenceCapture();
  const before = JSON.stringify(manifest);
  assert.equal(parseSiteManifest(manifest), manifest);
  assert.equal(JSON.stringify(manifest), before);
  delete manifest.captureProvenance;
  delete manifest.siteIntel.techStack.coverage;
  delete manifest.linkHealth.updatedAt;
  assert.equal(parseSiteManifest(manifest), manifest);
});

check('technology coverage rejects malformed displayed text, counts, and source URLs', () => {
  for (const key of ['selection', 'securityHeadersScope']) {
    for (const value of [{}, [], 1, true, null, undefined]) {
      const manifest = evidenceCapture();
      manifest.siteIntel.techStack.coverage[key] = value;
      assert.throws(() => parseSiteManifest(manifest), /invalid technology coverage/, key);
    }
  }
  for (const key of ['sampledPages', 'capturedHtmlPages']) {
    for (const value of [{}, [], '1', -1, Infinity, NaN, null, undefined]) {
      const manifest = evidenceCapture();
      manifest.siteIntel.techStack.coverage[key] = value;
      assert.throws(() => parseSiteManifest(manifest), /invalid technology coverage/, key);
    }
  }
  for (const value of [null, [], 'coverage']) {
    const manifest = evidenceCapture();
    manifest.siteIntel.techStack.coverage = value;
    assert.throws(() => parseSiteManifest(manifest), /invalid technology coverage/);
  }
  for (const value of [null, {}, [null], [{}], 'https://fixture.invalid']) {
    const manifest = evidenceCapture();
    manifest.siteIntel.techStack.coverage.sourceUrls = value;
    assert.throws(() => parseSiteManifest(manifest), /invalid technology coverage/);
  }
});

check('capture provenance rejects malformed nested runtime and displayed scalars', () => {
  const paths = [
    ['engineSha256'], ['configuration'], ['runtime'], ['runtime', 'pythonVersion'],
    ['runtime', 'platform'], ['runtime', 'pythonExecutable'], ['runtime', 'packages'],
    ['engineFiles'], ['browserEvidence'],
  ];
  for (const keys of paths) {
    for (const value of [null, [], 1, true]) {
      const manifest = evidenceCapture();
      const target = keys.length === 1 ? manifest.captureProvenance : manifest.captureProvenance.runtime;
      target[keys.at(-1)] = value;
      assert.throws(() => parseSiteManifest(manifest), /invalid capture (provenance|runtime|engine files|browser evidence)/, keys.join('.'));
    }
  }
  for (const keys of [['engineSha256'], ['runtime', 'pythonVersion'], ['runtime', 'platform'], ['runtime', 'pythonExecutable'], ['browserEvidence']]) {
    const manifest = evidenceCapture();
    const target = keys.length === 1 ? manifest.captureProvenance : manifest.captureProvenance.runtime;
    target[keys.at(-1)] = {};
    assert.throws(() => parseSiteManifest(manifest), /invalid capture (provenance|runtime|browser evidence)/, keys.join('.'));
  }
  for (const value of [null, [], 'provenance']) {
    const manifest = evidenceCapture();
    manifest.captureProvenance = value;
    assert.throws(() => parseSiteManifest(manifest), /invalid capture provenance/);
  }
  for (const key of ['packages', 'engineFiles']) {
    const manifest = evidenceCapture();
    const target = key === 'packages' ? manifest.captureProvenance.runtime : manifest.captureProvenance;
    target[key] = { unexpected: {} };
    assert.throws(() => parseSiteManifest(manifest), /invalid capture (runtime|engine files)/);
  }
});

check('link update dates reject objects and invalid timestamps before formatting', () => {
  for (const value of [{}, [], 1, true, null, '', 'not-a-date']) {
    const manifest = evidenceCapture();
    manifest.linkHealth.updatedAt = value;
    assert.throws(() => parseSiteManifest(manifest), /invalid link check date/);
  }
});

check('all retained captures still validate without mutation', () => {
  // Private captures are never committed, so a fresh clone has none to check.
  const files = (fs.existsSync('sites') ? fs.readdirSync('sites', { withFileTypes: true }) : [])
    .filter(entry => entry.isDirectory())
    .map(entry => path.join('sites', entry.name, '_site-graph.json'))
    .filter(file => fs.existsSync(file));
  if (files.length === 0) { console.log('[SKIP] No retained captures found, skipping capture compatibility check.'); return; }
  for (const file of files) {
    const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
    const before = JSON.stringify(manifest);
    assert.equal(parseSiteManifest(manifest), manifest, file);
    assert.equal(JSON.stringify(manifest), before, file);
  }
});

console.log('Resource validation: ' + count + ' deterministic cases passed.');
