#!/usr/bin/env node
// Unit checks for the discovery checklist and scorecard. Compiles the TS module with esbuild in memory.
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const out = await build({ entryPoints: ['src/data/discoveryChecklist.ts'], bundle: true, format: 'esm', write: false, platform: 'node' });
const mod = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64'));

const base = {
  nodes: [{ seoIssues: [] }],
  sitemaps: [{ url: 'https://a.test/sitemap.xml' }],
  stats: { sitemapUrlsTotal: 10 },
  robotsPolicy: { state: 'parsed', canCrawl: true, reason: 'ok' },
  linkHealth: { brokenLinks: [], serverErrors: [], uncheckedCount: 0 },
  siteIntel: {
    techStack: { securityHeaders: { present: ['HSTS'], missing: [] } },
    aiReadiness: {
      endpoints: { llmsTxt: true, llmsFullTxt: false, aiCatalogJson: false, securityTxt: true, adsTxt: false },
      validation: { llmsTxt: { valid: true, issues: [] }, securityTxt: { valid: true, issues: [], expires: '2027-01-01T00:00:00+00:00' } },
      blockedAiBots: [],
      sitemapHygiene: { broken: [], unavailable: [], redirect: [], noindex: [], undeclaredSitemaps: [] },
    },
  },
};
let { rows, score } = mod.buildDiscoveryChecklist(base);
assert.ok(rows.find((r) => r.id === 'llms').state === 'ok');
assert.deepEqual(score.filter((s) => s.id !== 'performance').map((s) => s.state), ['pass', 'pass', 'pass', 'pass', 'pass']);
assert.equal(score.find((s) => s.id === 'performance').state, 'unknown');

const bad = structuredClone(base);
bad.siteIntel.aiReadiness.endpoints.llmsTxt = false;
bad.siteIntel.aiReadiness.endpoints.securityTxt = false;
bad.sitemaps = [];
bad.linkHealth.brokenLinks = [{}];
({ rows, score } = mod.buildDiscoveryChecklist(bad));
assert.equal(rows.find((r) => r.id === 'llms').state, 'missing');
assert.ok(rows.find((r) => r.id === 'llms').fix.startsWith('# '));
assert.equal(rows.find((r) => r.id === 'sitemap').state, 'missing');
assert.equal(score.find((s) => s.id === 'links').state, 'fail');
assert.equal(score.find((s) => s.id === 'crawlability').state, 'warn');

const hc = structuredClone(base);
hc.siteIntel.techStack.securityHeaders.consistency = { sampledPages: 4, headers: [], inconsistent: ['CSP'], notes: [] };
({ rows, score } = mod.buildDiscoveryChecklist(hc));
assert.equal(score.find((r) => r.id === 'security').state, 'warn');
assert.match(score.find((r) => r.id === 'security').detail, /1 inconsistent across 4 sampled pages/);

const perf = (mutate) => { const m = structuredClone(base); mutate(m); return mod.buildDiscoveryChecklist(m).score.find((r) => r.id === 'performance'); };
assert.equal(perf((m) => { m.nodes = [{ seoIssues: [], responseTimeMs: 200, htmlBytes: 40000 }]; m.siteIntel.techStack.httpCompression = 'br'; }).state, 'pass');
assert.equal(perf((m) => { m.nodes = [{ seoIssues: [], responseTimeMs: 1000 }]; }).state, 'warn');
assert.equal(perf((m) => { m.nodes = [{ seoIssues: [], responseTimeMs: 2500 }]; }).state, 'fail');
assert.equal(perf((m) => { m.nodes = [{ seoIssues: [], responseTimeMs: 100 }]; m.siteIntel.techStack.httpCompression = null; }).state, 'warn');
assert.equal(perf((m) => { m.nodes = [{ seoIssues: [], responseTimeMs: 100, htmlBytes: 2_000_000 }]; m.siteIntel.techStack.httpCompression = 'gzip'; }).state, 'warn');
assert.match(perf((m) => { m.nodes = [{ seoIssues: [], responseTimeMs: 100 }]; }).detail, /not Core Web Vitals/);
const nd = mod.buildDiscoveryChecklist(base).rows.find((r) => r.id === 'indexnow');
assert.equal(nd.state, 'unknown');
assert.equal(nd.badge, 'Not detectable');

const sc = structuredClone(base);
sc.siteIntel.aiReadiness.siteChecks = { httpToHttps: { state: 'fail', detail: 'HTTP serves content without redirecting to HTTPS.' }, soft404: { state: 'ok', detail: 'ok' } };
sc.siteIntel.aiReadiness.robotsFindings = { blanketDisallow: true, blocksAssets: [], hasSitemapLine: true, contentSignal: null };
({ rows, score } = mod.buildDiscoveryChecklist(sc));
assert.equal(rows.find((r) => r.id === 'site-httpToHttps').state, 'warn');
assert.equal(score.find((r) => r.id === 'security').state, 'fail');
assert.equal(score.find((r) => r.id === 'crawlability').state, 'fail');

// Legacy capture with no intel must not throw.
({ rows, score } = mod.buildDiscoveryChecklist({ nodes: [], sitemaps: [], stats: { sitemapUrlsTotal: 0 } }));
assert.ok(rows.length >= 2 && score.length === 6);
console.log('[PASS] discovery checklist and scorecard: 4 groups of assertions');
