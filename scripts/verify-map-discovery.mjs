import assert from 'node:assert/strict';
import { build } from 'esbuild';

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const { buildDiscoveryStops, chooseDiscoveryNode, discoveryConnections } = await load('src/data/mapDiscovery.ts');
const { PREVIEW_SITE_MANIFEST: fixture } = await load('src/data/demoSite.ts');
const { attentionNodeIds, mapSummary, restingLabelIds, topAuthorityIds } = await load('src/data/mapAttention.ts');
const { computeSiteLayouts } = await load('src/data/globeLayout.ts');
const { buildSiteAudit } = await load('src/data/siteAudit.ts');
const clone = () => structuredClone(fixture);
let count = 0;
function check(name, fn) { fn(); count++; console.log('[PASS] ' + name); }
check('highlights are unique, drawn from visible nodes, and do not mutate the capture', () => {
  const manifest = clone();
  const before = JSON.stringify(manifest);
  const visible = manifest.nodes.filter(node => node.kind !== 'external-domain');
  const stops = buildDiscoveryStops(visible);
  assert.ok(stops.length >= 4);
  assert.equal(new Set(stops.map(stop => stop.node.id)).size, stops.length);
  assert.ok(stops.every(stop => visible.includes(stop.node)));
  assert.equal(stops[0].node.kind, 'home');
  assert.equal(JSON.stringify(manifest), before);
});
check('empty or single-node maps have no invented stops or surprise destination', () => {
  assert.deepEqual(buildDiscoveryStops([]), []);
  const home = fixture.nodes.find(node => node.kind === 'home');
  assert.equal(buildDiscoveryStops([home]).length, 1);
  assert.equal(chooseDiscoveryNode([home], new Set(), home.id), null);
});
check('surprise chooses unvisited visible nodes before repeats and skips the current stop', () => {
  const nodes = fixture.nodes.slice(0, 4);
  const visited = new Set(nodes.slice(0, 3).map(node => node.id));
  assert.equal(chooseDiscoveryNode(nodes, visited, nodes[0].id, 0).id, nodes[3].id);
  assert.notEqual(chooseDiscoveryNode(nodes, new Set(nodes.map(node => node.id)), nodes[0].id, 0).id, nodes[0].id);
  assert.ok(nodes.includes(chooseDiscoveryNode(nodes, new Set(), null, NaN)));
});
check('unknown click depths do not become an invented deep-route highlight', () => {
  const nodes = clone().nodes.map(node => ({ ...node, clickDepth: null }));
  assert.ok(buildDiscoveryStops(nodes).every(stop => stop.label !== 'Take the scenic route'));
});
check('real link connections exclude sitemap hierarchy and hidden navigation', () => {
  const manifest = clone();
  const [a, b, c] = manifest.nodes;
  manifest.edges = [
    { id: 'structure', source: a.id, target: b.id, kind: 'sitemap-hierarchy' },
    { id: 'nav', source: a.id, target: c.id, kind: 'internal-chrome' },
  ];
  const visible = new Set(manifest.nodes.map(node => node.id));
  assert.deepEqual(discoveryConnections(manifest, a.id, visible, false), []);
  assert.equal(discoveryConnections(manifest, a.id, visible, true)[0].node.id, c.id);
});
check('bidirectional links merge into one peer with the outgoing anchor', () => {
  const manifest = clone();
  const [a, b] = manifest.nodes;
  manifest.edges = [
    { id: 'in', source: b.id, target: a.id, kind: 'internal-body', anchor: 'Incoming anchor' },
    { id: 'out', source: a.id, target: b.id, kind: 'internal-body', anchor: 'Outgoing anchor' },
  ];
  const result = discoveryConnections(manifest, a.id, new Set([a.id, b.id]), false);
  assert.equal(result.length, 1);
  assert.equal(result[0].direction, 'both');
  assert.equal(result[0].anchor, 'Outgoing anchor');
  assert.deepEqual(discoveryConnections(manifest, a.id, new Set([a.id]), false), []);
});
check('attention pages come from attention-tone findings and failed pages only', () => {
  const manifest = clone();
  const ids = attentionNodeIds(manifest);
  const legacy = manifest.nodes.find(node => node.url.endsWith('/legacy-migration'));
  assert.ok(ids.has(legacy.id), 'broken page with an attention finding is flagged');
  const reviewOnly = manifest.nodes.find(node => node.url.endsWith('/lcp-subparts'));
  assert.ok(!ids.has(reviewOnly.id), 'review findings do not flag a page');
  assert.ok(ids.size < manifest.nodes.filter(node => node.kind !== 'external-domain').length, 'not every page is flagged');
  manifest.audit.findings.push({ id: 'x', category: 'links', tone: 'attention', title: 'x', explanation: '', targets: [{ url: manifest.origin + '/services/' }] });
  const services = manifest.nodes.find(node => node.url === manifest.origin + '/services');
  assert.ok(attentionNodeIds(manifest).has(services.id), 'a trailing slash still matches the captured page');
  assert.equal(attentionNodeIds(null).size, 0);
});
check('summary counts attention items, broken links and domains without inventing data', () => {
  const manifest = clone();
  const summary = mapSummary(manifest);
  assert.equal(summary.pages, manifest.stats.pagesCrawled);
  const attentionItems = (m) => buildSiteAudit(m).findings.filter(f => f.tone === 'attention').reduce((n, f) => n + (f.totalTargets ?? f.targets.length), 0);
  assert.equal(summary.attention, attentionItems(manifest), 'toolbar counts match the Site audit panel');
  assert.ok(summary.attention > 0);
  assert.ok(summary.review > 0);
  assert.equal(summary.brokenLinks, manifest.nodes.filter(node => node.health === 'broken').length);
  assert.match(summary.brokenDetail, /Link checks were not recorded/);
  const legacy = { ...clone(), audit: undefined, linkHealth: { brokenLinks: [{}, {}], results: [], uncheckedCount: 0 } };
  const legacySummary = mapSummary(legacy);
  assert.equal(legacySummary.hasAudit, false);
  assert.equal(legacySummary.attention, attentionItems(legacy), 'legacy captures count the same findings the panel shows');
  assert.equal(legacySummary.brokenLinks, 2 + legacy.nodes.filter(node => node.health === 'broken').length);
});
check('resting labels keep home, sections, attention and the top pages, and label everything on small maps', () => {
  const manifest = clone();
  const visible = manifest.nodes.filter(node => node.kind !== 'external-domain');
  assert.equal(restingLabelIds(visible, new Set()).size, visible.length, 'small maps label every node');
  const many = Array.from({ length: 60 }, (_, i) => ({ ...visible[4], id: 'p' + i, path: '/p' + i, kind: 'page', authorityScore: i }));
  const nodes = [visible[0], visible[1], ...many];
  const ids = restingLabelIds(nodes, new Set(['p3']));
  assert.ok(ids.has(visible[0].id) && ids.has(visible[1].id), 'home and section hub keep labels');
  assert.ok(ids.has('p59') && ids.has('p50') && !ids.has('p49'), 'top ten by authority');
  assert.ok(ids.has('p3'), 'attention page keeps its label');
  assert.equal(ids.size, 13);
  assert.deepEqual([...topAuthorityIds(many, 2)], ['p59', 'p58']);
});
check('road layout uses only filled depth columns and spreads them across a wide frame', () => {
  const manifest = clone();
  const layouts = computeSiteLayouts(manifest);
  const ids = layouts.roadColumns.map(column => column.id);
  assert.deepEqual(ids, ['home', 'd1', 'd2', 'd3', 'unlinked', 'external']);
  const xs = layouts.roadColumns.map(column => column.x);
  assert.ok(xs.every((x, i) => i === 0 || x > xs[i - 1]), 'columns run left to right');
  assert.equal(layouts.roadColumns.reduce((n, column) => n + column.count, 0), manifest.nodes.length);
  const flat = { ...manifest, nodes: Array.from({ length: 40 }, (_, i) => ({ ...manifest.nodes[4], id: 'n' + i, url: 'https://x/' + i, path: '/' + i, kind: i ? 'page' : 'home', health: i ? 'healthy' : 'home', clickDepth: i ? 1 : 0 })), edges: [] };
  const wide = computeSiteLayouts(flat);
  assert.deepEqual(wide.roadColumns.map(column => column.id), ['home', 'd1'], 'empty columns are left out');
  const points = [...wide.road.values()];
  const width = Math.max(...points.map(p => p[0])) - Math.min(...points.map(p => p[0]));
  const height = Math.max(...points.map(p => p[1])) - Math.min(...points.map(p => p[1]));
  assert.ok(width / height > 1.2, 'a single crowded depth wraps into side-by-side columns: ' + (width / height).toFixed(2));
  assert.ok(new Set(points.map(p => p[0].toFixed(2))).size >= 3, 'depth 1 uses several sub-columns');
});
console.log('Map discovery: ' + count + ' deterministic data cases passed.');
