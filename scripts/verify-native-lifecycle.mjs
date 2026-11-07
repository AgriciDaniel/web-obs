#!/usr/bin/env node
/** Isolated native-host regressions. No real crawler, browser, install, or network. */
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { transformSync } = require('esbuild');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function loadSource(relative, stubs = {}) {
  const code = transformSync(fs.readFileSync(path.join(root, relative), 'utf8'), {
    loader: 'ts', format: 'cjs', target: 'es2022',
  }).code;
  const module = { exports: {} };
  const resolve = (name) => {
    assert.ok(Object.hasOwn(stubs, name), `Unexpected import in isolated test: ${name}`);
    return stubs[name];
  };
  new Function('require', 'module', 'exports', code)(resolve, module, module.exports);
  return module.exports;
}

const jsonl = loadSource('src/data/jsonl.ts');
const validation = loadSource('src/data/validateManifest.ts');
const pipelineProgress = loadSource('src/data/crawlProgress.ts');
const crawlErrors = loadSource('src/plugin/crawlErrors.ts');
const vaultResync = loadSource('src/plugin/vaultResync.ts');
const fixture = {
  schemaVersion: '1.0.0', siteId: 'example.test', domain: 'example.test', origin: 'https://example.test',
  capturedAt: '2026-11-01T00:00:00Z', elapsedSec: 0,
  stats: Object.fromEntries(['pagesCrawled', 'sitemapsFound', 'sitemapUrlsTotal', 'internalEdges',
    'externalDomains', 'externalEdges', 'localImagesDownloaded', 'orphanPages', 'unlistedPages',
    'brokenOrRedirectPages'].map((name) => [name, 0])),
  nodes: [], edges: [], sections: [], sitemaps: [],
};
const flush = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
const options = { url: 'https://example.test', renderMode: 'never' };
const complete = (extra = {}) => JSON.stringify({ event: 'complete', siteId: fixture.siteId, ...extra });

class FakeChild extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  exitCode = null;
  signalCode = null;
  killed = false;
  signals = [];
  pid = 4242;
  stdinText = [];
  stdin = { once() { return this; }, end: (text) => { this.stdinText.push(text); } };
  kill(signal) { this.killed = true; this.signals.push(signal); return true; }
  close(code = 0, signal = null) {
    this.exitCode = code;
    this.signalCode = signal;
    this.emit('close', code, signal);
  }
  write(text) { this.stdout.emit('data', Buffer.from(text)); }
}

async function hostHarness({ deferred = false, manifest = fixture, spawnError = false, settings = {}, platform = 'linux' } = {}) {
  const children = [], spawnCalls = [], ready = [], readinessCalls = [], progress = [], saved = [], notices = [], timers = new Set();
  let host, mounts = 0;
  class Adapter { getBasePath() { return '/synthetic-vault'; } }
  class ItemView {
    constructor() {
      this.app = { vault: { adapter: new Adapter(), getName: () => 'Synthetic' }, workspace: { on: () => ({}) } };
      this.contentEl = { empty() {}, addClass() {}, clientWidth: 640, clientHeight: 400, ownerDocument: { defaultView: {} } };
    }
    registerEvent() {}
  }
  const childProcess = { spawn: (command, args, options) => { spawnCalls.push({ command, args, options }); if (spawnError) throw new Error('synthetic spawn refusal'); const child = new FakeChild(); children.push(child); return child; } };
  const engineStop = loadSource('src/plugin/engineStop.ts', { 'node:child_process': childProcess, 'node:process': { platform } });
  const stubs = {
    'node:fs': { existsSync: () => true, readdirSync: () => [{ name: fixture.siteId, isDirectory: () => true }], readFileSync: () => JSON.stringify(manifest) },
    'node:path': path,
    'node:timers': {
      setTimeout: (callback) => { const timer = { callback, unref() {} }; timers.add(timer); return timer; },
      clearTimeout: (timer) => timers.delete(timer),
    },
    'node:child_process': childProcess,
    './engineStop': engineStop,
    obsidian: { ItemView, FileSystemAdapter: Adapter, Notice: class { constructor(message) { notices.push(message); } }, TFile: class {}, normalizePath: (value) => value },
    '../App': {},
    '../obsidian/hostAdapter': {
      WEB_OBS_VIEW_TYPE: 'web-obs-site-globe', sanitizeExternalHttpUrl: () => null,
      sanitizeVaultRelativePath: (value) => value,
      mountSiteGlobeApp: (_element, adapter) => { host = adapter; mounts += 1; return { unmount() {} }; },
    },
    './pythonRuntime': { ensurePythonEngineReady: (_vault, _script, _binary, _status, readinessOptions) => {
      readinessCalls.push(readinessOptions);
      if (!deferred) return Promise.resolve({ pythonBin: 'synthetic-python' });
      return new Promise((resolve) => ready.push({ resolve, options: readinessOptions }));
    } },
    './windowVisibility': { WindowVisibilityBinding: class { bind() {} dispose() {} } },
    '../data/jsonl': jsonl, '../data/validateManifest': validation,
    '../data/crawlProgress': pipelineProgress,
    './crawlErrors': crawlErrors,
    './vaultResync': vaultResync,
  };
  const { SiteGlobeView } = loadSource('src/plugin/SiteGlobeView.ts', stubs);
  const view = new SiteGlobeView({}, { manifest: { dir: 'synthetic-plugin' }, settings: {
    pythonBinary: 'synthetic-python', defaultMaxPages: 20, downloadImages: false,
    renderMode: 'never', themeBehavior: 'dark', defaultViewMode: 'globe', ...settings,
  } });
  await view.onOpen();
  host.subscribeHostEvents({ onCrawlProgress: (value) => progress.push({ ...value }), onSitesChanged: (...values) => saved.push(values) });
  return { view, host, children, spawnCalls, ready, readinessCalls, progress, saved, notices, timers, get mounts() { return mounts; } };
}

let passed = 0;
async function test(name, run) {
  await run();
  passed += 1;
  console.log(`[PASS] ${name}`);
}

await test('saved-link continuation passes the saved ID and needs HTTP-only readiness', async () => {
  const h = await hostHarness({ settings: { renderMode: 'auto' } });
  const job = h.host.startCrawl({ url: 'https://example.test', continueLinksSiteId: 'example.test' });
  await flush();
  assert.equal(h.readinessCalls.length, 1);
  assert.equal(h.readinessCalls[0].renderMode, 'never');
  assert.equal(h.children.length, 1);
  const args = h.spawnCalls[0].args;
  assert.equal(args[1], 'example.test');
  assert.ok(args.includes('--continue-links'));
  assert.equal(args.includes('--render'), false);
  assert.equal(args.includes('--max-pages'), false);
  h.children[0].write(complete({ operation: 'continue-links' })); h.children[0].close();
  assert.equal((await job).siteId, fixture.siteId);
  assert.equal(h.saved.length, 1);
  assert.equal(h.progress.at(-1).phase, 'done');
});

await test('unsafe continuation IDs are rejected before readiness and spawn', async () => {
  const h = await hostHarness();
  for (const id of ['../escape', '/absolute', '', 'a'.repeat(181), ['example.test'], null]) {
    await assert.rejects(h.host.startCrawl({ url: 'https://example.test', continueLinksSiteId: id }), /Invalid saved site ID/);
  }
  assert.equal(h.readinessCalls.length, 0);
  assert.equal(h.spawnCalls.length, 0);
  assert.equal(h.saved.length, 0);
});

await test('saved-link continuation uses the same cancellation and stale-output ownership', async () => {
  const h = await hostHarness();
  const job = h.host.startCrawl({ url: 'https://example.test', continueLinksSiteId: 'example.test' });
  await flush();
  const child = h.children[0];
  h.host.cancelCrawl();
  assert.equal(await job, null);
  assert.deepEqual(child.signals, ['SIGTERM']);
  child.write(complete({ operation: 'continue-links' })); child.close();
  assert.equal(h.saved.length, 0);
  assert.equal(h.progress.at(-1).phase, 'cancelled');
});

await test('native imageMode all forwards the explicit CLI image variant option', async () => {
  const h = await hostHarness();
  const job = h.host.startCrawl({ ...options, imageMode: 'all' });
  await flush();
  const args = h.spawnCalls[0].args;
  assert.equal(args[args.indexOf('--image-mode') + 1], 'all');
  assert.equal(args.includes('--continue-links'), false);
  h.children[0].write(complete()); h.children[0].close();
  assert.ok(await job);
});

await test('close during readiness prevents a late spawn and remount', async () => {
  const h = await hostHarness({ deferred: true });
  const job = h.view.runCrawlFromPlugin(options);
  await h.view.onClose();
  assert.equal(h.ready[0].options.signal.aborted, true);
  h.ready[0].resolve({ pythonBin: 'synthetic-python' });
  assert.equal(await job, null);
  assert.equal(h.children.length, 0);
  h.view.onResize();
  assert.equal(h.mounts, 1);
  assert.equal(await h.view.runCrawlFromPlugin(options), null);
});

await test('explicit cancellation during readiness is terminal without a spawn', async () => {
  const h = await hostHarness({ deferred: true });
  const job = h.view.runCrawlFromPlugin(options);
  h.host.cancelCrawl();
  h.ready[0].resolve({ pythonBin: 'synthetic-python' });
  assert.equal(await job, null);
  assert.equal(h.children.length, 0);
  assert.equal(h.progress.at(-1).phase, 'cancelled');
  assert.equal(h.progress.at(-1).error, null);
});

await test('superseded preparation cannot overwrite the latest request', async () => {
  const h = await hostHarness({ deferred: true });
  const old = h.view.runCrawlFromPlugin(options);
  const current = h.view.runCrawlFromPlugin(options);
  assert.equal(h.ready[0].options.signal.aborted, true);
  h.ready[0].resolve({ pythonBin: 'synthetic-python' });
  assert.equal(await old, null);
  assert.equal(h.children.length, 0);
  h.ready[1].resolve({ pythonBin: 'synthetic-python' });
  await flush();
  assert.equal(h.children.length, 1);
  h.children[0].write(complete()); h.children[0].close();
  assert.equal((await current).siteId, fixture.siteId);
});

await test('old close and output cannot clear a newer process handle', async () => {
  const h = await hostHarness();
  const old = h.view.runCrawlFromPlugin(options); await flush();
  const first = h.children[0];
  const current = h.view.runCrawlFromPlugin(options); await flush();
  const second = h.children[1];
  assert.equal(await old, null);
  first.write(`${JSON.stringify({ event: 'error', message: 'stale error' })}\n`); first.close(1);
  assert.equal(h.view.activeChild, second);
  assert.notEqual(h.progress.at(-1).message, 'stale error');
  await h.view.onClose();
  assert.equal(await current, null);
  assert.deepEqual(second.signals, ['SIGTERM']);
  second.close(null, 'SIGTERM');
  assert.equal(h.saved.length, 0);
});

await test('owned children that ignore termination receive a bounded escalation', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  const child = h.children[0]; h.host.cancelCrawl();
  assert.equal(await job, null);
  for (const timer of h.timers) timer.callback();
  assert.deepEqual(child.signals, ['SIGTERM', 'SIGKILL']);
  child.close(null, 'SIGKILL');
  assert.equal(h.timers.size, 0);
  assert.equal(h.progress.at(-1).phase, 'cancelled');
});

await test('every capture can be cancelled through standard input', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  assert.ok(h.spawnCalls[0].args.includes('--cancel-on-stdin'));
  h.children[0].write(complete()); h.children[0].close();
  assert.ok(await job);
  const linkJob = h.host.startCrawl({ url: 'https://example.test', continueLinksSiteId: 'example.test' }); await flush();
  assert.ok(h.spawnCalls[1].args.includes('--cancel-on-stdin'));
  h.children[1].write(complete({ operation: 'continue-links' })); h.children[1].close();
  assert.ok(await linkJob);
});

await test('on Windows a cancel is written to standard input, then the whole process tree is ended', async () => {
  const h = await hostHarness({ platform: 'win32' });
  const job = h.view.runCrawlFromPlugin(options); await flush();
  const child = h.children[0]; h.host.cancelCrawl();
  assert.equal(await job, null);
  assert.deepEqual(child.signals, [], 'no SIGTERM, which Windows turns into an instant kill');
  assert.deepEqual(child.stdinText, ['cancel\n']);
  for (const timer of h.timers) timer.callback();
  const killer = h.spawnCalls.at(-1);
  assert.equal(killer.command, 'taskkill');
  assert.deepEqual(killer.args, ['/PID', '4242', '/T', '/F']);
  child.close(1);
  assert.equal(h.timers.size, 0);
  assert.equal(h.progress.at(-1).phase, 'cancelled');
});

await test('pipeline progress keeps page, media and link counters independent', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  const event = {
    event: 'pipeline_progress', phase: 'crawl', stage: 'media', elapsedSec: 8.25,
    currentUrl: 'https://example.test/image.png', message: 'Downloading page media',
    pages: { discovered: 20, completed: 3, active: 2, queued: 15, failed: 1, skipped: 4, bytes: 1024 },
    media: { discovered: 100, completed: 70, active: 3, queued: 25, failed: 2, skipped: 5, bytes: 8192 },
    links: { discovered: 30, completed: 11, active: 1, queued: 18, failed: 2, skipped: 3, bytes: 512 },
  };
  h.children[0].write(JSON.stringify(event) + '\n');
  const state = h.progress.at(-1);
  assert.deepEqual(state.pipeline.pages, event.pages);
  assert.deepEqual(state.pipeline.media, event.media);
  assert.deepEqual(state.pipeline.links, event.links);
  assert.equal(state.currentPage, 3);
  assert.equal(state.maxPages, 20);
  assert.equal(state.currentUrl, event.currentUrl);
  assert.equal(state.pipeline.elapsedSec, 8.25);
  assert.equal(state.pipeline.stage, 'media');
  assert.equal(state.message, event.message);
  assert.equal(state.running, true);
  h.children[0].write(complete()); h.children[0].close();
  assert.ok(await job);
});

await test('pipeline progress clamps invalid lane values without contaminating other lanes', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  h.children[0].write(JSON.stringify({
    event: 'pipeline_progress', phase: 'crawl', elapsedSec: -4, stage: 9, currentUrl: 42,
    pages: { discovered: -1, completed: NaN, active: Infinity, queued: '99', failed: null, bytes: -25 },
    media: null, links: { discovered: 4, completed: 2, active: 1, queued: 1, failed: 0, skipped: 0, bytes: 64 },
  }) + '\n');
  const state = h.progress.at(-1);
  const empty = { discovered: 0, completed: 0, active: 0, queued: 0, failed: 0, skipped: 0, bytes: 0 };
  assert.deepEqual(state.pipeline.pages, empty);
  assert.deepEqual(state.pipeline.media, empty);
  assert.equal(state.pipeline.links.completed, 2);
  assert.equal(state.pipeline.links.bytes, 64);
  assert.equal(state.currentPage, 0);
  assert.equal(state.currentUrl, '');
  assert.equal(state.pipeline.elapsedSec, 0);
  assert.equal(state.pipeline.stage, 'crawl');
  h.children[0].write(complete()); h.children[0].close();
  assert.ok(await job);
});

await test('compile progress clears the prior page URL and keeps completed lane counts', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  const child = h.children[0];
  child.write(JSON.stringify({ event: 'crawl_progress', current: 2, maxPages: 20, url: 'https://example.test/last-page' }) + '\n');
  assert.equal(h.progress.at(-1).currentUrl, 'https://example.test/last-page');
  child.write(JSON.stringify({ event: 'pipeline_progress', phase: 'compile', stage: 'links', message: 'Checking links', pages: { completed: 2 }, media: { completed: 8 }, links: { completed: 5 } }) + '\n');
  assert.equal(h.progress.at(-1).phase, 'compile');
  assert.equal(h.progress.at(-1).currentUrl, '');
  assert.equal(h.progress.at(-1).pipeline.media.completed, 8);
  child.write(JSON.stringify({ event: 'phase', phase: 'compile', message: 'Writing capture' }) + '\n');
  assert.equal(h.progress.at(-1).currentUrl, '');
  assert.equal(h.progress.at(-1).pipeline.links.completed, 5);
  child.write(complete()); child.close();
  assert.ok(await job);
});

await test('legacy sitemap and page progress events remain compatible without pipeline events', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  const child = h.children[0];
  child.write(JSON.stringify({ event: 'sitemap_progress', sitemapsFound: 2, urlsDiscovered: 44, sitemapUrl: 'https://example.test/sitemap.xml' }) + '\n');
  assert.equal(h.progress.at(-1).sitemapsFound, 2);
  assert.equal(h.progress.at(-1).sitemapUrlsCount, 44);
  child.write(JSON.stringify({ event: 'sitemap_done', sitemapsCount: 3, sitemapUrlsCount: 21 }) + '\n');
  child.write(JSON.stringify({ event: 'crawl_progress', current: 4, maxPages: 20, url: 'https://example.test/page-4' }) + '\n');
  const state = h.progress.at(-1);
  assert.equal(state.sitemapsFound, 3);
  assert.equal(state.sitemapUrlsCount, 21);
  assert.equal(state.currentPage, 4);
  assert.equal(state.phase, 'crawl');
  assert.equal(state.currentUrl, 'https://example.test/page-4');
  assert.equal(state.pipeline, undefined);
  child.write(JSON.stringify({ event: 'phase', phase: 'compile', message: 'Compiling' }) + '\n');
  assert.equal(h.progress.at(-1).currentUrl, '');
  child.write(complete()); child.close();
  assert.ok(await job);
});

await test('split UTF-8 and final unterminated JSONL complete only after validation', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  const child = h.children[0];
  const bytes = Buffer.from(`${JSON.stringify({ event: 'phase', phase: 'compile', message: 'Café' })}\n${complete()}`);
  const split = bytes.indexOf(Buffer.from('é')) + 1;
  child.stdout.emit('data', bytes.subarray(0, split)); child.stdout.emit('data', bytes.subarray(split));
  assert.ok(h.progress.some((value) => value.message === 'Café'));
  assert.equal(h.progress.some((value) => value.phase === 'done'), false);
  child.close();
  assert.equal((await job).siteId, fixture.siteId);
  assert.equal(h.saved.length, 1);
  assert.equal(h.progress.at(-1).phase, 'done');
  assert.equal(h.progress.at(-1).running, false);
});

for (const [name, payload, code, pattern] of [
  ['nonzero exit after complete', complete(), 1, /code 1/],
  ['error before complete', `${JSON.stringify({ event: 'error', message: 'synthetic engine refusal' })}\n${complete()}`, 0, /synthetic engine refusal/],
  ['missing completion event', `${JSON.stringify({ event: 'phase', phase: 'crawl' })}\n`, 0, /without a completion/],
  ['malformed JSON', '{not valid JSON}\n', 1, /invalid JSON/],
  ['invalid completion ID', complete({ siteId: '../escape' }), 0, /invalid capture ID/],
  ['event following completion', `${complete()}\n${JSON.stringify({ event: 'phase', phase: 'compile' })}\n`, 0, /events after completion/],
  ['oversized event', 'x'.repeat(1024 * 1024 + 1), 1, /line limit/],
]) {
  await test(`${name} cannot report success`, async () => {
    const h = await hostHarness();
    const job = h.view.runCrawlFromPlugin(options); await flush();
    h.children[0].write(payload); h.children[0].close(code);
    assert.equal(await job, null);
    assert.equal(h.saved.length, 0);
    assert.equal(h.progress.at(-1).phase, 'error');
    assert.match(h.progress.at(-1).message, pattern);
  });
}

await test('malformed persisted manifest is refused before React receives it', async () => {
  const h = await hostHarness({ manifest: { siteId: fixture.siteId } });
  const job = h.view.runCrawlFromPlugin(options); await flush();
  h.children[0].write(complete()); h.children[0].close();
  assert.equal(await job, null);
  assert.equal(h.saved.length, 0);
  assert.match(h.progress.at(-1).message, /could not be validated/);
});

await test('cancellation during manifest loading suppresses stale publication', async () => {
  const h = await hostHarness(); let resolveLoad;
  h.view.loadVaultSiteManifest = () => new Promise((resolve) => { resolveLoad = resolve; });
  const job = h.view.runCrawlFromPlugin(options); await flush();
  h.children[0].write(complete()); h.children[0].close(); await flush();
  h.host.cancelCrawl(); resolveLoad(fixture);
  assert.equal(await job, null); await flush();
  assert.equal(h.saved.length, 0);
  assert.equal(h.progress.at(-1).phase, 'cancelled');
});

await test('spawn exceptions settle the request instead of rejecting or hanging', async () => {
  const h = await hostHarness({ spawnError: true });
  assert.equal(await h.view.runCrawlFromPlugin(options), null);
  assert.match(h.progress.at(-1).message, /synthetic spawn refusal/);
});

await test('partial completion stays visibly partial after a valid save', async () => {
  const h = await hostHarness();
  const job = h.view.runCrawlFromPlugin(options); await flush();
  h.children[0].write(complete({ captureStatus: 'partial' })); h.children[0].close();
  assert.ok(await job);
  assert.match(h.progress.at(-1).message, /Partial capture/);
  assert.match(h.notices.at(-1), /Partial capture/);
});

function runtimeHarness(capabilities, { deferred = false, existingPaths = [], execError = false } = {}) {
  const calls = [];
  const runtime = loadSource('src/plugin/pythonRuntime.ts', {
    'node:fs': { existsSync: (candidate) => existingPaths.includes(candidate) }, 'node:path': path, 'node:process': process,
    'node:child_process': { execFile(command, args, settings, callback) {
      calls.push({ command, args, settings });
      if (deferred) settings.signal.addEventListener('abort', () => callback(new Error('aborted'), '', ''), { once: true });
      else if (execError) callback(new Error('synthetic executable unavailable'), '', '');
      else callback(null, `startup log\n${JSON.stringify({ webObsCapabilities: capabilities })}\n`, '');
    } },
  });
  return { runtime, calls };
}
const defaultPy = process.platform === 'win32' ? 'python' : 'python3.14';
const core = { missingCore: [], pythonSupported: true, playwrightAvailable: false, chromiumExecutableAvailable: false };

await test('Python below 3.14 is refused and a supported runtime passes the same bounded probe', async () => {
  for (const pythonSupported of [false, true]) {
    const capabilities = { ...core, pythonSupported };
    const { runtime, calls } = runtimeHarness(capabilities);
    const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3.14', undefined, { renderMode: 'never' });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, defaultPy);
    assert.match(calls[0].args[2], /sys\.version_info\s*>=\s*\(3,\s*14\)/);
    assert.equal(result.pythonBin, defaultPy);
    if (pythonSupported) assert.equal(result.error, undefined);
    else {
      assert.match(result.error, /Python 3\.14\+/);
      assert.match(result.error, /Nothing was installed automatically/);
    }
    const dependencyCheck = runtimeHarness(capabilities);
    assert.equal(await dependencyCheck.runtime.checkPythonDeps('python3.14', '/synthetic', { renderMode: 'never' }), pythonSupported);
    assert.equal(dependencyCheck.calls.length, 1);
  }
});

await test('default Python aliases prefer an existing local environment and preserve candidate order', async () => {
  const venvPython = (directory) => path.join(directory, ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python3']));
  const script = '/synthetic/plugins/web-obs/engine/crawl_site.py';
  const candidates = [venvPython('/synthetic/plugins/web-obs/engine/.venv'), venvPython('/synthetic/engine/.venv'), venvPython('/synthetic/.venv')];
  for (const alias of ['', 'python', 'python3', 'python3.14', ' python3.14 ']) {
    for (let first = 0; first < candidates.length; first += 1) {
      const { runtime, calls } = runtimeHarness(core, { existingPaths: candidates.slice(first) });
      const result = await runtime.ensurePythonEngineReady('/synthetic', script, alias, undefined, { renderMode: 'never' });
      assert.equal(result.error, undefined);
      assert.equal(result.pythonBin, candidates[first]);
      assert.equal(calls.length, 1);
      assert.equal(calls[0].command, candidates[first]);
    }
    const { runtime, calls } = runtimeHarness(core);
    const result = await runtime.ensurePythonEngineReady('/synthetic', script, alias, undefined, { renderMode: 'never' });
    assert.equal(result.pythonBin, defaultPy);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, defaultPy);
  }
});

await test('an unusable selected runtime fails without installation or an interpreter fallback', async () => {
  const local = path.join('/synthetic/engine/.venv', ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python3']));
  for (const capabilities of [{ ...core, pythonSupported: false }, { ...core, missingCore: ['requests'] }]) {
    const { runtime, calls } = runtimeHarness(capabilities, { existingPaths: [local] });
    const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3.14', undefined, { renderMode: 'never' });
    assert.equal(result.pythonBin, local);
    assert.match(result.error, /Python 3\.14\+/);
    assert.match(result.error, /Nothing was installed automatically/);
    assert.deepEqual(calls.map(call => call.command), [local]);
  }
  for (const configured of ['python3.14', '/chosen/python3.14']) {
    const { runtime, calls } = runtimeHarness(core, { execError: true });
    const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', configured, undefined, { renderMode: 'never' });
    const expectedBin = configured === 'python3.14' ? defaultPy : configured;
    assert.equal(result.pythonBin, expectedBin);
    assert.match(result.error, /Python 3\.14\+/);
    assert.match(result.error, /Nothing was installed automatically/);
    assert.deepEqual(calls.map(call => call.command), [expectedBin]);
  }
  const { runtime, calls } = runtimeHarness(core, { existingPaths: [local] });
  const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', '/chosen/python3.14', undefined, { renderMode: 'never' });
  assert.equal(result.pythonBin, '/chosen/python3.14');
  assert.equal(result.error, undefined);
  assert.deepEqual(calls.map(call => call.command), ['/chosen/python3.14']);
});

await test('HTTP-only readiness makes one bounded probe and never installs dependencies', async () => {
  const { runtime, calls } = runtimeHarness(core);
  assert.equal((await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3', undefined, { renderMode: 'never' })).error, undefined);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].args.slice(0, 2), ['-B', '-c']);
  assert.equal(calls[0].args.at(-2), 'never');
  assert.equal(calls[0].args.at(-1), '/synthetic/engine');
  assert.equal(calls[0].settings.timeout, 20000);
  assert.equal(calls[0].settings.maxBuffer, 65536);
});

await test('render modes require both Playwright and a Chromium executable', async () => {
  for (const mode of ['auto', 'always']) {
    for (const capabilities of [core, { ...core, playwrightAvailable: true }]) {
      const { runtime, calls } = runtimeHarness(capabilities);
      const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3', undefined, { renderMode: mode });
      assert.match(result.error, /Playwright module|Compatible Chromium/);
      assert.equal(calls.length, 1);
    }
  }
  const { runtime } = runtimeHarness({ ...core, playwrightAvailable: true, chromiumExecutableAvailable: true });
  assert.equal((await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3', undefined, { renderMode: 'auto' })).error, undefined);
});

await test('browser diagnostics preserve the actual discovery error', async () => {
  const error = 'The configured PLAYWRIGHT_BROWSERS_PATH has no compatible executable.';
  const { runtime, calls } = runtimeHarness({ ...core, playwrightAvailable: true, browserError: error });
  const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/plugins/web-obs/engine/crawl_site.py', 'python3', undefined, { renderMode: 'auto' });
  assert.equal(result.error, error);
  assert.equal(calls[0].args.at(-1), '/synthetic/plugins/web-obs/engine');
});

await test('missing core modules and unstructured output fail without bootstrap', async () => {
  for (const value of [{ ...core, missingCore: ['requests'] }, null]) {
    const { runtime, calls } = runtimeHarness(value);
    const result = await runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3');
    assert.ok(result.error);
    assert.equal(calls.length, 1);
    assert.match(result.error, /Nothing was installed automatically/);
  }
});

await test('runtime capability subprocess inherits cancellation', async () => {
  const { runtime, calls } = runtimeHarness(core, { deferred: true });
  const controller = new AbortController();
  const pending = runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3', undefined, { signal: controller.signal });
  controller.abort();
  assert.match((await pending).error, /cancelled/);
  assert.equal(calls[0].settings.signal.aborted, true);
  const early = runtimeHarness(core);
  await early.runtime.ensurePythonEngineReady('/synthetic', '/synthetic/engine/crawl_site.py', 'python3', undefined, { signal: controller.signal });
  assert.equal(early.calls.length, 0);
});

console.log(`\nNative lifecycle and capability regressions passed: ${passed} cases. All processes and host APIs were mocked.`);
