import assert from 'node:assert/strict';
import { build } from 'esbuild';

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const { buildDiscoveryStops, chooseDiscoveryNode, discoveryConnections } = await load('src/data/mapDiscovery.ts');
const { PREVIEW_SITE_MANIFEST: fixture } = await load('src/data/demoSite.ts');
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
console.log('Map discovery: ' + count + ' deterministic data cases passed.');
