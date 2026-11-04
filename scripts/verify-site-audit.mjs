import assert from 'node:assert/strict';
import fs from 'node:fs';
import { build } from 'esbuild';

const output = await build({ entryPoints: ['src/data/siteAudit.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
const { buildSiteAudit, filterAuditFindings } = await import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
const FIXTURE_PATH = 'sites/agricidaniel.com/_site-graph.json';
if (!fs.existsSync(FIXTURE_PATH)) {
  // Captures are private and never committed, so a fresh clone has none.
  console.log(`[SKIP] Site audit checks need a saved capture at ${FIXTURE_PATH}. Capture a site, then rerun.`);
  process.exit(0);
}
const fixture = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));
const internal = fixture.nodes.filter(node => node.kind !== 'external-domain');
const sum = rows => rows.reduce((total, row) => total + row.count, 0);
const bucket = (rows, id) => rows.find(row => row.id === id).count;
// The saved capture may come from any engine version. Tests start from its graph without the
// 0.2.0 engine audit and add one where they need it, so results do not depend on that version.
const clone = () => { const copy = structuredClone(fixture); delete copy.audit; delete copy.issueCatalog; return copy; };
let passed = 0;
function test(name, fn) { fn(); passed++; console.log('[PASS] ' + name); }

test('retained capture chart counts are complete, internal-only, and do not mutate evidence', () => {
  const manifest = clone();
  const before = JSON.stringify(manifest);
  const audit = buildSiteAudit(manifest);
  assert.equal(audit.pageCount, internal.length);
  assert.equal(sum(audit.pageSections), internal.length);
  assert.equal(sum(audit.linkDistribution), audit.linkTotal);
  assert.equal(sum(audit.mediaDistribution), manifest.resources.length);
  assert.equal(sum(audit.mediaTypes), manifest.resources.length);
  assert.equal(bucket(audit.mediaDistribution, 'saved'), manifest.resources.filter(resource => resource.localPath).length);
  assert.equal(JSON.stringify(manifest), before);
  assert.ok(audit.notAssessed.includes('Core Web Vitals field data'));
  assert.ok(audit.notAssessed.includes('Full accessibility conformance'));
  assert.equal(audit.engineFindings, false);
  assert.equal(audit.extras, null);
  assert.equal(Object.hasOwn(audit, 'score'), false);
});

test('zero and missing observations remain no data without invented findings or coverage', () => {
  const manifest = clone();
  manifest.nodes = []; manifest.edges = []; manifest.sections = [];
  delete manifest.resources; delete manifest.linkHealth; delete manifest.siteIntel;
  const audit = buildSiteAudit(manifest);
  assert.equal(audit.pageCount, 0);
  assert.equal(audit.linkTotal, 0);
  assert.equal(audit.linkAttempted, null);
  assert.equal(audit.linksObserved, false);
  assert.equal(audit.mediaObserved, false);
  assert.equal(audit.imageMetricPages, 0);
  assert.equal(audit.headers, null);
  assert.deepEqual(audit.findings, []);
  assert.equal(sum(audit.linkDistribution), 0);
  assert.equal(sum(audit.mediaDistribution), 0);
  manifest.resources = []; manifest.linkHealth = { totalCount: 0, checkedCount: 0, results: [] };
  assert.equal(buildSiteAudit(manifest).linkTotal, 0);
});

test('inconclusive, unchecked and absent link results never become working or broken links', () => {
  const manifest = clone();
  const row = (url, status, statusCode) => ({ url, status, statusCode, reason: 'Fixture observation' });
  manifest.linkHealth = { totalCount: 8, checkedCount: 5, results: [
    row('https://fixture.invalid/ok', 'ok', 200), row('https://fixture.invalid/gone', 'broken', 410),
    row('https://fixture.invalid/server', 'server-error', 503), row('https://fixture.invalid/blocked', 'unknown', 403),
    row('https://fixture.invalid/unchecked', 'unchecked', null), row('https://fixture.invalid/legacy-blocked', 'broken', 429),
  ] };
  const audit = buildSiteAudit(manifest);
  assert.equal(bucket(audit.linkDistribution, 'ok'), 1);
  assert.equal(bucket(audit.linkDistribution, 'broken'), 1);
  assert.equal(bucket(audit.linkDistribution, 'unknown'), 2);
  assert.equal(bucket(audit.linkDistribution, 'unchecked'), 1);
  assert.equal(bucket(audit.linkDistribution, 'unrecorded'), 2);
  assert.equal(sum(audit.linkDistribution), 8);
  assert.equal(audit.findings.find(group => group.id === 'link-unknown').tone, 'coverage');
  assert.equal(audit.findings.find(group => group.id === 'link-unchecked').tone, 'coverage');
  assert.equal(audit.findings.find(group => group.id === 'link-server').tone, 'review');
});

test('legacy HEAD-only missing responses need GET confirmation even when unchecked count is zero', () => {
  const manifest = clone();
  const row = (path, statusCode, method, status = 'broken') => ({ url: `https://fixture.invalid/${path}`, status, statusCode, method, reason: `HTTP ${statusCode}` });
  manifest.linkHealth = { totalCount: 4, checkedCount: 4, uncheckedCount: 0, results: [
    row('head-missing', 404, 'HEAD'), row('head-gone', 410, 'HEAD'),
    row('get-missing', 404, 'GET'), row('responded', 200, 'GET', 'ok'),
  ] };
  const audit = buildSiteAudit(manifest);
  assert.equal(bucket(audit.linkDistribution, 'unknown'), 2);
  assert.equal(bucket(audit.linkDistribution, 'broken'), 1);
  assert.equal(bucket(audit.linkDistribution, 'ok'), 1);
  assert.equal(audit.linkUnchecked, 0);
  assert.equal(audit.linkPending, 2);
  const inconclusive = audit.findings.find(group => group.id === 'link-unknown');
  assert.equal(inconclusive.tone, 'coverage');
  assert.equal(inconclusive.targets.length, 2);
  assert.ok(inconclusive.targets.every(target => target.detail.includes('GET confirmation is still required')));
  manifest.linkHealth.results[0] = row('head-missing', 200, 'GET', 'ok');
  manifest.linkHealth.results[1] = row('head-gone', 410, 'GET');
  const confirmed = buildSiteAudit(manifest);
  assert.equal(bucket(confirmed.linkDistribution, 'unknown'), 0);
  assert.equal(bucket(confirmed.linkDistribution, 'broken'), 2);
  assert.equal(bucket(confirmed.linkDistribution, 'ok'), 2);
  assert.equal(confirmed.linkPending, 0);
});

test('intentionally unselected and reference-only resources are separate from failures', () => {
  const manifest = clone();
  const states = ['saved', 'reference', 'not-selected', 'not-requested', 'budget-skipped', 'unavailable', 'queued'];
  manifest.resources = states.map((state, i) => ({ id: `resource-${i}`, url: `https://fixture.invalid/${i}`, type: 'image', downloadState: state, references: [], localPath: state === 'saved' ? 'sites/fixture/assets/a.png' : null }));
  const audit = buildSiteAudit(manifest);
  assert.equal(bucket(audit.mediaDistribution, 'saved'), 1);
  assert.equal(bucket(audit.mediaDistribution, 'intentional'), 2);
  assert.equal(bucket(audit.mediaDistribution, 'reference'), 1);
  assert.equal(bucket(audit.mediaDistribution, 'unavailable'), 1);
  assert.equal(bucket(audit.mediaDistribution, 'budget'), 1);
  assert.equal(sum(audit.mediaDistribution), states.length);
});

test('page findings group actual affected pages and deduplicate overlapping health flags', () => {
  const manifest = clone();
  const [a, b] = internal;
  manifest.nodes = [
    { ...a, health: 'orphan', seoIssues: ['orphan-page', 'missing-title', 'missing-title', 'images-missing-alt (2)'], imagesCount: 5, imagesMissingAlt: 2, statusCode: 200 },
    { ...b, health: 'healthy', seoIssues: ['missing-title'], statusCode: 200 },
  ];
  delete manifest.nodes[1].imagesMissingAlt;
  manifest.edges = []; delete manifest.linkHealth; delete manifest.siteIntel;
  const audit = buildSiteAudit(manifest);
  assert.equal(audit.findings.find(group => group.id === 'orphan').targets.length, 1);
  assert.match(audit.findings.find(group => group.id === 'orphan').explanation, /disconnected page groups/);
  assert.equal(audit.findings.filter(group => group.id === 'seo:orphan-page').length, 0);
  assert.equal(audit.findings.find(group => group.id === 'seo:missing-title').targets.length, 2);
  assert.equal(audit.findings.find(group => group.id === 'missing-alt').targets[0].pageId, a.id);
  assert.equal(audit.imageMetricPages, 1);
  assert.equal(audit.imagesMissingAlt, 2);
  assert.equal(audit.findings.filter(group => group.id.startsWith('seo:images-missing-alt')).length, 0);
});

test('link findings preserve affected URLs and resolve source pages from references or exact graph edges', () => {
  const manifest = clone();
  const [a, b] = internal;
  manifest.nodes = [a, b];
  manifest.resources = [{ id: 'fixture', url: 'https://fixture.invalid/media', type: 'image', references: [{ pageUrl: a.url, role: 'image' }] }];
  manifest.edges = [{ id: 'edge-fixture', source: b.id, target: 'external-fixture', kind: 'external', targetUrl: 'https://fixture.invalid/article' }];
  manifest.linkHealth = { totalCount: 2, checkedCount: 2, results: ['media', 'article'].map(path => ({ url: `https://fixture.invalid/${path}`, status: 'broken', statusCode: 404, reason: 'HTTP 404' })) };
  const group = buildSiteAudit(manifest).findings.find(group => group.id === 'link-broken');
  assert.equal(group.targets.find(target => target.url.endsWith('/media')).sourcePageId, a.id);
  assert.equal(group.targets.find(target => target.url.endsWith('/article')).sourcePageId, b.id);
  assert.ok(group.targets.every(target => target.url.startsWith('https://fixture.invalid/')));
});

test('search and category filtering preserve groups, narrow targets, and do not mutate findings', () => {
  const manifest = clone();
  manifest.nodes = internal.slice(0, 2).map((node, i) => ({ ...node, title: `Needle page ${i}`, seoIssues: ['missing-title'] }));
  const audit = buildSiteAudit(manifest);
  const before = JSON.stringify(audit);
  const matches = filterAuditFindings(audit.findings, 'pages', 'NEEDLE PAGE 0');
  assert.equal(matches.find(group => group.id === 'seo:missing-title').targets.length, 1);
  assert.ok(filterAuditFindings(audit.findings, 'links', 'Needle page').every(group => group.category === 'links'));
  assert.deepEqual(filterAuditFindings(audit.findings, 'all', 'nonexistent-needle-value'), []);
  assert.equal(JSON.stringify(audit), before);
});

test('homepage header scope is explicit and absent coverage is not upgraded to site-wide assessment', () => {
  const manifest = clone();
  const home = { ...internal[0], kind: 'home', seoIssues: [] };
  manifest.nodes = [home];
  manifest.siteIntel = { techStack: { securityHeaders: { present: ['HSTS'], missing: ['CSP'] }, coverage: { securityHeadersScope: 'Homepage response only' } } };
  const audit = buildSiteAudit(manifest);
  assert.equal(audit.headers.scope, 'Homepage response only');
  assert.equal(audit.findings.find(group => group.id === 'headers-missing').targets[0].pageId, home.id);
  delete manifest.siteIntel.techStack.coverage;
  assert.match(buildSiteAudit(manifest).headers.scope, /Legacy scope details were not recorded/);
  delete manifest.siteIntel;
  assert.equal(buildSiteAudit(manifest).headers, null);
});

test('legacy capture uses issue catalog titles and categories when present', () => {
  const manifest = clone();
  manifest.nodes = [{ ...internal[0], health: 'healthy', seoIssues: ['mixed-content (2)', 'brand-new-signal'] }];
  manifest.edges = []; delete manifest.linkHealth; delete manifest.siteIntel; delete manifest.audit;
  manifest.issueCatalog = { 'mixed-content': { category: 'security', tone: 'attention', title: 'Mixed content', explanation: 'Insecure subresources.' } };
  const audit = buildSiteAudit(manifest);
  const mixed = audit.findings.find(group => group.id === 'seo:mixed-content');
  assert.equal(mixed.title, 'Mixed content');
  assert.equal(mixed.category, 'security');
  assert.equal(mixed.tone, 'attention');
  assert.equal(audit.findings.find(group => group.id === 'seo:brand-new-signal').category, 'pages');
});

test('engine findings replace node-derived page findings and map targets to pages and sources', () => {
  const manifest = clone();
  const [a, b] = internal;
  manifest.nodes = [{ ...a, health: 'orphan', seoIssues: ['missing-title', 'images-missing-alt (2)'], imagesMissingAlt: 2, imagesCount: 4, statusCode: 200 }, { ...b, seoIssues: [] }];
  manifest.edges = []; delete manifest.linkHealth; delete manifest.siteIntel;
  const many = Array.from({ length: 200 }, (_, i) => ({ url: `https://fixture.invalid/img-${i}.png`, detail: `${i} KB`, sourceUrl: b.url }));
  manifest.audit = {
    findings: [
      { id: 'seo:missing-title', category: 'pages', tone: 'attention', title: 'Missing title', explanation: 'Engine text.', targets: [{ url: a.url + '/', detail: '' }] },
      { id: 'link-opportunity', category: 'links', tone: 'review', title: 'Internal link opportunities', explanation: 'Heuristic.', targets: [{ url: a.url, sourceUrl: b.url, detail: 'Mentions x' }] },
      { id: 'image-oversized', category: 'images', tone: 'review', title: 'Large images', explanation: 'Resize.', targets: many, targetCount: 450 },
      { id: 'mystery', category: 'not-a-category', tone: 'coverage', title: 'Unknown category', explanation: 'Falls back.', targets: [{ url: a.url }] },
    ],
    linkOpportunities: [{ sourceUrl: b.url, targetUrl: a.url, phrase: 'x' }], linkFixes: [],
    duplicates: { titles: [{ value: 't', urls: [a.url, b.url] }], descriptions: [], h1: [], exactContent: [], nearContent: [] },
    tasks: { open: 5, ticked: 1, resolved: 2, notRechecked: 0 },
  };
  const audit = buildSiteAudit(manifest);
  assert.equal(audit.engineFindings, true);
  assert.equal(audit.findings.filter(group => group.id === 'orphan' || group.id === 'missing-alt').length, 0);
  assert.equal(audit.findings.filter(group => group.id === 'seo:missing-title').length, 1);
  const title = audit.findings.find(group => group.id === 'seo:missing-title');
  assert.equal(title.explanation, 'Engine text.');
  assert.equal(title.targets[0].pageId, a.id, 'trailing slash variant still maps to the page');
  const opportunity = audit.findings.find(group => group.id === 'link-opportunity').targets[0];
  assert.equal(opportunity.pageId, a.id);
  assert.equal(opportunity.sourcePageId, b.id);
  const images = audit.findings.find(group => group.id === 'image-oversized');
  assert.equal(images.targets.length, 200);
  assert.equal(images.totalTargets, 450);
  assert.equal(images.targets[0].sourcePageId, b.id);
  assert.equal(audit.findings.find(group => group.id === 'mystery').category, 'pages');
  assert.equal(audit.findingCount, 1 + 1 + 450 + 1);
  assert.equal(audit.imagesMissingAlt, 2);
  assert.deepEqual(audit.extras, { linkOpportunities: 1, linkFixes: 0, duplicateGroups: 1, tasks: { open: 5, ticked: 1, resolved: 2, notRechecked: 0 } });
  const narrowed = filterAuditFindings(audit.findings, 'images', 'img-3.png');
  assert.equal(narrowed[0].totalTargets, undefined);
  assert.ok(audit.scopeNotes.some(note => note.includes('axe-core')));
});

test('engine path still reports link checks and header observations', () => {
  const manifest = clone();
  const home = { ...internal[0], kind: 'home', seoIssues: [] };
  manifest.nodes = [home]; manifest.edges = [];
  manifest.audit = { findings: [] };
  manifest.linkHealth = { totalCount: 1, checkedCount: 1, results: [{ url: 'https://fixture.invalid/gone', status: 'broken', statusCode: 404, reason: 'HTTP 404' }] };
  manifest.siteIntel = { techStack: { securityHeaders: { present: [], missing: ['CSP'] } } };
  const audit = buildSiteAudit(manifest);
  assert.ok(audit.findings.some(group => group.id === 'link-broken'));
  assert.ok(audit.findings.some(group => group.id === 'headers-missing'));
});

console.log(`Site audit: ${passed} deterministic data cases passed. No network or scan was performed.`);
