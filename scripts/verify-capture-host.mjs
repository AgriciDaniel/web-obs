#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { build } from 'esbuild';
import { createServer } from 'vite';

const root = process.cwd();
assert.doesNotMatch(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), /<link[^>]+(?:href=["']https?:|preconnect)/i, 'Preview must not load remote fonts or stylesheets');
assert.doesNotMatch(fs.readFileSync(path.join(root, 'src/styles/theme.css'), 'utf8'), /@import\s+(?:url\()?['"]?https?:/i, 'UI must not import hosted stylesheets');
const require = createRequire(import.meta.url);
let fetchImpl = globalThis.fetch;
async function load(entry) {
  const output = await build({ entryPoints: [path.join(root, entry)], bundle: true, write: false, platform: 'node', format: 'cjs', logLevel: 'silent' });
  const module = { exports: {} };
  vm.runInNewContext(output.outputFiles[0].text, {
    module, exports: module.exports, require, process, Buffer, console,
    TextDecoder, TextEncoder, AbortController, URL, setTimeout, clearTimeout,
    fetch: (...args) => fetchImpl(...args),
  });
  return module.exports;
}
const { createStandaloneHost } = await load('src/obsidian/hostAdapter.ts');
const { JsonlDecoder } = await load('src/data/jsonl.ts');
const { parseSiteManifest } = await load('src/data/validateManifest.ts');
const { PREVIEW_SITE_MANIFEST } = await load('src/data/demoSite.ts');
const { webObsDevApiPlugin } = await load('src/server/captureApi.ts');
const good = JSON.parse(JSON.stringify(PREVIEW_SITE_MANIFEST));
assert.ok(good, 'Demo capture must be exported');
parseSiteManifest(good);
// Private captures are never committed, so a fresh clone has no sites folder.
const sitesDir = path.join(root, 'sites');
for (const directory of fs.existsSync(sitesDir) ? fs.readdirSync(sitesDir, { withFileTypes: true }) : []) {
  const file = path.join(root, 'sites', directory.name, '_site-graph.json');
  if (directory.isDirectory() && fs.existsSync(file)) parseSiteManifest(JSON.parse(fs.readFileSync(file, 'utf8')));
}
assert.throws(() => parseSiteManifest({ ...good, nodes: [{}] }));
assert.throws(() => parseSiteManifest({ ...good, captureStatus: 'magic' }));
const records = [];
const decoder = new JsonlDecoder((event) => records.push(event));
const bytes = new TextEncoder().encode('{"event":"phase","message":"Bună 日本"}\n{"event":"complete"}');
for (const byte of bytes) decoder.push(new Uint8Array([byte]));
decoder.finish();
assert.equal(records[0].message, 'Bună 日本');
assert.equal(records[1].event, 'complete');
assert.throws(() => new JsonlDecoder(() => {}).push('bad\n'));
assert.throws(() => new JsonlDecoder(() => {}).push('x'.repeat(1024 * 1024 + 1)));
console.log('[PASS] Persisted captures, malformed graph rejection, UTF-8 and final JSONL line.');

const complete = JSON.stringify({ event: 'complete', siteId: good.siteId });
for (const continuing of [false, true]) for (const [stream, expected] of [[complete, 'done'], [complete + '\n', 'done'], ['{"event":"phase","phase":"crawl"}\n', 'error'], ['{"event":"error","message":"Fixture error"}', 'error'], ['nonsense\n', 'error']]) {
  const progress = [];
  const calls = [];
  const endpoint = continuing ? '/__web_obs/continue-links' : '/__web_obs/crawl';
  fetchImpl = async (url, settings) => {
    calls.push({ url: String(url), settings });
    return String(url) === endpoint ? new Response(stream) : Response.json(good);
  };
  const host = createStandaloneHost();
  host.subscribeHostEvents({ onCrawlProgress: (event) => progress.push(event) });
  const result = await host.startCrawl({ url: good.origin, ...(continuing ? { continueLinksSiteId: good.siteId } : {}) });
  assert.equal(calls[0].url, endpoint);
  assert.equal(calls[0].settings.method, 'POST');
  assert.equal(JSON.parse(calls[0].settings.body).continueLinksSiteId, continuing ? good.siteId : undefined);
  assert.equal(progress.at(-1).phase, expected);
  assert.equal(progress.at(-1).running, false);
  assert.equal(progress[0].maxPages, 250);
  assert.equal(Boolean(result), expected === 'done');
  if (continuing && expected === 'done') assert.match(progress.at(-1).message, /Saved link checks updated/);
}
for (const continuing of [false, true]) {
  const host = createStandaloneHost();
  const progress = [];
  host.subscribeHostEvents({ onCrawlProgress: (event) => progress.push(event) });
  let oldController;
  let oldSignal;
  let requests = 0;
  const endpoint = continuing ? '/__web_obs/continue-links' : '/__web_obs/crawl';
  const continuation = continuing ? { continueLinksSiteId: good.siteId } : {};
  fetchImpl = async (url, settings) => {
    if (String(url) !== endpoint) return Response.json(good);
    assert.equal(JSON.parse(settings.body).continueLinksSiteId, continuing ? good.siteId : undefined);
    requests++;
    if (requests > 1) return new Response(complete);
    oldSignal = settings.signal;
    return new Response(new ReadableStream({ start(controller) { oldController = controller; } }));
  };
  const old = host.startCrawl({ url: 'https://old.example', ...continuation });
  await new Promise((resolve) => setImmediate(resolve));
  host.cancelCrawl();
  assert.equal(oldSignal.aborted, true);
  assert.equal(progress.at(-1).phase, 'cancelled');
  const current = await host.startCrawl({ url: good.origin, ...continuation });
  oldController.enqueue(new TextEncoder().encode('{"event":"error","message":"stale"}\n'));
  oldController.close();
  assert.equal(await old, null);
  assert.equal(current.siteId, good.siteId);
  assert.equal(progress.at(-1).phase, 'done');
}
async function exerciseProgress(events) {
  const progress = [];
  fetchImpl = async (url) => String(url).endsWith('/crawl')
    ? new Response(events.map((event) => JSON.stringify(event)).concat(complete).join('\n'))
    : Response.json(good);
  const host = createStandaloneHost();
  host.subscribeHostEvents({ onCrawlProgress: (event) => progress.push(event) });
  const manifest = await host.startCrawl({ url: good.origin, maxPages: 20 });
  assert.equal(manifest.siteId, good.siteId);
  assert.equal(progress.at(-1).phase, 'done');
  return progress;
}
const plain = (value) => JSON.parse(JSON.stringify(value));
{
  const event = {
    event: 'pipeline_progress', phase: 'crawl', stage: 'media', elapsedSec: 8.25,
    currentUrl: good.origin + '/image.png', message: 'Collecting independent lanes',
    pages: { discovered: 20, completed: 3, active: 2, queued: 15, failed: 1, skipped: 4, bytes: 1024 },
    media: { discovered: 100, completed: 70, active: 3, queued: 25, failed: 2, skipped: 5, bytes: 8192 },
    links: { discovered: 30, completed: 11, active: 1, queued: 18, failed: 2, skipped: 3, bytes: 512 },
  };
  const progress = await exerciseProgress([event]);
  const state = progress.find((value) => value.message === event.message);
  assert.deepEqual(plain(state.pipeline.pages), event.pages);
  assert.deepEqual(plain(state.pipeline.media), event.media);
  assert.deepEqual(plain(state.pipeline.links), event.links);
  assert.equal(state.currentPage, 3);
  assert.equal(state.maxPages, 20);
  assert.equal(state.currentUrl, event.currentUrl);
  assert.equal(state.pipeline.elapsedSec, 8.25);
  assert.equal(state.pipeline.stage, 'media');
}
{
  const progress = await exerciseProgress([{
    event: 'pipeline_progress', phase: 'crawl', stage: false, elapsedSec: -1,
    currentUrl: 99, message: 'Invalid lane metrics',
    pages: { discovered: -5, completed: Infinity, active: NaN, queued: '8', failed: null, bytes: -100 },
    media: null, links: { discovered: 4, completed: 2, active: 1, queued: 1, failed: 0, skipped: 0, bytes: 64 },
  }]);
  const state = progress.find((value) => value.message === 'Invalid lane metrics');
  const empty = { discovered: 0, completed: 0, active: 0, queued: 0, failed: 0, skipped: 0, bytes: 0 };
  assert.deepEqual(plain(state.pipeline.pages), empty);
  assert.deepEqual(plain(state.pipeline.media), empty);
  assert.equal(state.pipeline.links.completed, 2);
  assert.equal(state.pipeline.links.bytes, 64);
  assert.equal(state.pipeline.elapsedSec, 0);
  assert.equal(state.pipeline.stage, 'crawl');
  assert.equal(state.currentPage, 0);
  assert.equal(state.currentUrl, '');
}
{
  const progress = await exerciseProgress([
    { event: 'crawl_progress', current: 2, maxPages: 20, url: good.origin + '/last-page' },
    { event: 'phase', phase: 'compile', message: 'Legacy compile transition' },
    { event: 'pipeline_progress', phase: 'compile', stage: 'links', message: 'Pipeline compile transition', pages: { completed: 2 }, media: { completed: 8 }, links: { completed: 5 } },
  ]);
  assert.ok(progress.some((value) => value.currentUrl === good.origin + '/last-page'));
  for (const message of ['Legacy compile transition', 'Pipeline compile transition']) {
    const state = progress.find((value) => value.message === message);
    assert.equal(state.phase, 'compile');
    assert.equal(state.currentUrl, '');
  }
  const state = progress.find((value) => value.message === 'Pipeline compile transition');
  assert.equal(state.pipeline.media.completed, 8);
  assert.equal(state.pipeline.links.completed, 5);
}
{
  const progress = await exerciseProgress([
    { event: 'sitemap_progress', sitemapsFound: 2, urlsDiscovered: 44, sitemapUrl: good.origin + '/sitemap.xml' },
    { event: 'sitemap_done', sitemapsCount: 3, sitemapUrlsCount: 21 },
    { event: 'crawl_progress', current: 4, maxPages: 20, url: good.origin + '/page-4' },
    { event: 'phase', phase: 'compile', message: 'Legacy-only compile' },
  ]);
  const state = progress.find((value) => value.currentUrl === good.origin + '/page-4');
  assert.equal(state.sitemapsFound, 3);
  assert.equal(state.sitemapUrlsCount, 21);
  assert.equal(state.currentPage, 4);
  assert.equal(state.maxPages, 20);
  assert.equal(state.pipeline, undefined);
  assert.equal(progress.find((value) => value.message === 'Legacy-only compile').currentUrl, '');
}
console.log('[PASS] Standalone pipeline lanes, invalid metric clamping, compile URL clearing and legacy progress compatibility.');
fetchImpl = globalThis.fetch;
console.log('[PASS] Standalone crawl and saved-link continuation endpoint, payload, EOF, errors, cancellation and stale stream ownership.');

let fixtureRequests = 0;
const fixture = http.createServer((req, res) => {
  fixtureRequests++;
  if (req.url === '/robots.txt') { res.setHeader('Content-Type', 'text/plain'); res.end('User-agent: *\nAllow: /\n'); }
  else if (req.url === '/') { res.setHeader('Content-Type', 'text/html'); res.end('<html><head><title>Capture fixture</title></head><body><main><h1>Local fixture</h1><p>Direct website content.</p></main></body></html>'); }
  else { res.statusCode = 404; res.end('Not found'); }
});
await new Promise((resolve) => fixture.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${fixture.address().port}`;
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'web-obs-host-'));
const originalAllowlist = process.env.WEB_OBS_LOCAL_TARGETS;
let preview;
try {
  fs.symlinkSync(path.join(root, 'engine'), path.join(temporary, 'engine'), 'dir');
  fs.mkdirSync(path.join(temporary, '.obsidian'));
  process.env.WEB_OBS_LOCAL_TARGETS = `127.0.0.1:${fixture.address().port}`;
  process.chdir(temporary);
  const plugin = webObsDevApiPlugin();
  process.chdir(root);
  preview = await createServer({ configFile: false, root: temporary, plugins: [plugin], server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await preview.listen();
  const endpoint = `http://127.0.0.1:${preview.httpServer.address().port}`;
  const response = await fetch(endpoint + '/__web_obs/crawl', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: origin, maxPages: 1, renderMode: 'never', downloadImages: false }) });
  assert.equal(response.status, 200);
  const events = (await response.text()).trim().split('\n').map((line) => JSON.parse(line));
  const laneEvent = events.findLast((event) => event.event === 'pipeline_progress');
  assert.ok(laneEvent, 'Actual crawler must emit pipeline progress');
  assert.equal(events.filter((event) => event.event === 'complete').length, 1, 'Completion must be emitted once: ' + events.map((event) => event.event).join(',') + ' | last: ' + JSON.stringify(events.slice(-3)).slice(-2500));
  assert.ok(events.findLastIndex((event) => event.event === 'pipeline_progress') < events.length - 1, 'Pipeline progress must precede completion');
  assert.equal(laneEvent.pages.completed, 1);
  assert.equal(laneEvent.media.completed, 0);
  assert.equal(laneEvent.links.completed, 0);
  for (const lane of ['pages', 'media', 'links']) {
    for (const name of ['discovered', 'completed', 'active', 'queued', 'failed', 'skipped', 'bytes']) {
      assert.ok(Number.isFinite(laneEvent[lane][name]) && laneEvent[lane][name] >= 0, `${lane}.${name} must be a nonnegative finite count`);
    }
  }
  assert.equal(events.at(-1).event, 'complete', JSON.stringify(events.at(-1)));
  const id = events.at(-1).siteId;
  const saved = await fetch(endpoint + '/__web_obs/site?id=' + encodeURIComponent(id));
  const manifest = parseSiteManifest(await saved.json());
  assert.equal(manifest.stats.pagesCrawled, 1);
  const beforeContinuationRequests = fixtureRequests;
  const continued = await fetch(endpoint + '/__web_obs/continue-links', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: origin + '/must-not-recrawl', continueLinksSiteId: id }),
  });
  assert.equal(continued.status, 200);
  const continuationEvents = (await continued.text()).trim().split('\n').map(line => JSON.parse(line));
  assert.equal(continuationEvents.filter(event => event.event === 'complete').length, 1);
  assert.equal(continuationEvents.at(-1).event, 'complete');
  assert.equal(continuationEvents.at(-1).operation, 'continue-links');
  assert.equal(continuationEvents.at(-1).siteId, id);
  const updated = parseSiteManifest(await (await fetch(endpoint + '/__web_obs/site?id=' + encodeURIComponent(id))).json());
  assert.equal(updated.capturedAt, manifest.capturedAt);
  assert.deepEqual(updated.nodes, manifest.nodes);
  assert.equal(updated.linkCheckSessions.length, (manifest.linkCheckSessions?.length ?? 0) + 1);
  assert.equal(fixtureRequests, beforeContinuationRequests, 'Continuation with no unchecked links must not recrawl HTML');
  for (const unsafe of ['../escape', '', ['valid-looking'], null]) {
    const invalid = await fetch(endpoint + '/__web_obs/continue-links', { method: 'POST', body: JSON.stringify({ url: origin, continueLinksSiteId: unsafe }) });
    assert.equal(invalid.status, 400);
    assert.match((await invalid.json()).error, /Invalid saved site ID/);
  }
  for (const route of ['crawl', 'continue-links']) {
    const valid = { url: origin, ...(route === 'continue-links' ? { continueLinksSiteId: id } : {}) };
    for (const imageMode of ['unknown', ['all'], {}, 0]) {
      const invalid = await fetch(endpoint + '/__web_obs/' + route, { method: 'POST', body: JSON.stringify({ ...valid, imageMode }) });
      assert.equal(invalid.status, 400);
      assert.match((await invalid.json()).error, /Invalid image variant mode/);
    }
    for (const headers of [{ Origin: 'https://outside.example' }, { 'Sec-Fetch-Site': 'cross-site' }]) {
      assert.equal((await fetch(endpoint + '/__web_obs/' + route, { method: 'POST', headers, body: JSON.stringify(valid) })).status, 403);
    }
  }
  assert.equal((await fetch(endpoint + '/__web_obs/site?id=..%2Fsecret')).status, 400);
  assert.equal((await fetch(endpoint + '/__web_obs/crawl', { method: 'POST', body: '{}' })).status, 400);
  assert.equal((await fetch(endpoint + '/__web_obs/crawl', { method: 'POST', headers: { Origin: 'https://outside.example' }, body: '{}' })).status, 403);
  assert.equal((await fetch(endpoint + '/__web_obs/crawl', { method: 'POST', body: 'x'.repeat(17000) })).status, 413);
  console.log('[PASS] Actual local preview streams crawl and continuation, reuses saved pages, and rejects unsafe IDs, image modes and cross-site requests.');
} finally {
  process.chdir(root);
  if (preview) await preview.close();
  fixture.closeAllConnections();
  await new Promise((resolve) => fixture.close(resolve));
  if (originalAllowlist === undefined) delete process.env.WEB_OBS_LOCAL_TARGETS;
  else process.env.WEB_OBS_LOCAL_TARGETS = originalAllowlist;
  fs.rmSync(temporary, { recursive: true, force: true });
}
