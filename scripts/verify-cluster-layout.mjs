import assert from 'node:assert/strict';
import { build } from 'esbuild';

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const { computeSiteLayouts } = await load('src/data/globeLayout.ts');

function node(id, kind, index) {
  return {
    id, kind, health: kind === 'home' ? 'home' : 'healthy', title: id, url: `https://example.test/${id}`,
    path: kind === 'home' ? '/' : `/${id}`, section: `s${index % 6}`, obsidianPath: `${id}.md`, statusCode: 200,
    inSitemap: true, urlDepth: 1, clickDepth: kind === 'home' ? 0 : 1, wordCount: 100,
    metaDescription: '', canonical: '', metaRobots: '', inlinksBody: 1,
  };
}

/** The home page links to every page and each page links to `linksPerPage` others. */
function linkedSite(pages, linksPerPage) {
  const nodes = [node('home', 'home', 0)];
  for (let i = 0; i < pages; i++) nodes.push(node(`p${i}`, 'page', i + 1));
  const edges = [];
  for (let i = 0; i < pages; i++) {
    edges.push({ id: `h${i}`, source: 'home', target: `p${i}`, kind: 'internal-body' });
    for (let j = 0; j < linksPerPage; j++) {
      edges.push({ id: `l${i}-${j}`, source: `p${i}`, target: `p${(i + j * 17 + 1) % pages}`, kind: 'internal-body' });
    }
  }
  return { domain: 'example.test', nodes, edges };
}

function widest(layout) {
  let max = 0;
  for (const [id, point] of layout) {
    for (const value of point) {
      assert.ok(Number.isFinite(value), `${id} has a finite coordinate`);
      max = Math.max(max, Math.abs(value));
    }
  }
  return max;
}

let count = 0;
function check(name, fn) { fn(); count++; console.log('[PASS] ' + name); }

check('a densely linked site keeps the cluster layout bounded', () => {
  const layouts = computeSiteLayouts(linkedSite(2000, 40));
  assert.equal(layouts.clusters.size, 2001);
  const max = widest(layouts.clusters);
  assert.ok(max < 200, `the layout stays compact (widest coordinate ${max.toFixed(1)})`);
});

check('pages that link only to a busy home page stay as close as before', () => {
  // A star: the home page has 50 links, each page has one. Before the stability fix the pages sat at a
  // radius of about 7.3; damping the home page's links for both ends pushed them out past 10.
  const nodes = [node('home', 'home', 0)];
  const edges = [];
  for (let i = 0; i < 50; i++) {
    nodes.push(node(`p${i}`, 'page', i + 1));
    edges.push({ id: `h${i}`, source: 'home', target: `p${i}`, kind: 'internal-body' });
  }
  const clusters = computeSiteLayouts({ domain: 'example.test', nodes, edges }).clusters;
  const radii = nodes.slice(1).map((page) => Math.hypot(...clusters.get(page.id))).sort((a, b) => a - b);
  const median = radii[radii.length >> 1];
  assert.ok(median < 8.5, `pages keep their pull toward home (median radius ${median.toFixed(2)})`);
});

check('the cluster layout is deterministic', () => {
  const site = linkedSite(120, 5);
  const a = computeSiteLayouts(site).clusters;
  const b = computeSiteLayouts(site).clusters;
  for (const [id, point] of a) assert.deepEqual(b.get(id), point);
});

console.log(`${count} cluster layout checks passed`);
