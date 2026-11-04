import assert from 'node:assert/strict';
import { build } from 'esbuild';

const output = await build({ entryPoints: ['src/plugin/compareSites.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
const { buildComparisonMarkdown, siteMetrics, comparisonNotePath } = await import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));

const page = (url, words, schema = [], extra = {}) => ({ id: url, kind: 'page', url, statusCode: 200, wordCount: words, schemaTypes: schema, ...extra });
const a = {
  siteId: 'a.com', domain: 'a.com', capturedAt: '2026-11-01T00:00:00Z', captureStatus: 'complete',
  stats: { medianResponseTimeMs: 120, orphanPages: 1, externalDomains: 3 },
  sections: [{ label: '/blog', pageCount: 2 }],
  nodes: [page('https://a.com/', 900, ['WebSite'], { pageChecks: { textRatio: 0.2, readability: { fleschReadingEase: 60 } } }), page('https://a.com/x', 100), { id: 'ext', kind: 'external-domain', url: 'https://z.com' }],
  audit: { findings: [{ category: 'content', targets: [{}, {}], targetCount: 2 }], linkOpportunities: [{}], linkFixes: [], duplicates: { titles: [{}], descriptions: [], exactContent: [], nearContent: [] }, keywords: { bigrams: [{ term: 'site audit' }] }, freshness: { stale: [] } },
  siteIntel: { aiReadiness: { endpoints: { llmsTxt: true }, aiBotsPolicy: { GPTBot: 'allowed' }, allowedAiBotsCount: 1 }, transport: { tls: { daysRemaining: 40 } },
    browserAudit: { pages: [{ lab: { lcpMs: 800 }, a11y: { violations: [{}] }, thirdParty: { hosts: [{ host: 'cdn.x' }] } }] } },
};
const b = { siteId: 'b.com', domain: 'b.com', capturedAt: '2026-11-02T00:00:00Z', stats: {}, sections: [], nodes: [page('https://b.com/', 300, ['Organization'])] };

const left = siteMetrics(a);
assert.equal(left.rows['Pages captured'], '2');
assert.equal(left.rows['Thin pages (under 200 words)'], '1 (50%)');
assert.equal(left.rows['Median text to HTML ratio'], '20%');
assert.equal(left.rows['Finding items: content'], '2');
assert.equal(left.rows['Browser sample median LCP (lab ms)'], '800');
const right = siteMetrics(b);
assert.equal(right.rows['Internal link opportunities'], 'No data', 'legacy captures without an audit show No data');
assert.equal(right.rows['TLS days remaining'], 'No data');
const md = buildComparisonMarkdown(a, b, '2026-11-03T00:00:00Z');
assert.match(md, /\| Pages captured \| 2 \| 1 \|/);
assert.match(md, /Only a\.com:\*\* WebSite/);
assert.match(md, /Only b\.com:\*\* Organization/);
const banned = [String.fromCharCode(0x2013), String.fromCharCode(0x2014)];
assert.ok(!banned.some((ch) => md.includes(ch)), 'no dashes in generated text');
assert.equal(comparisonNotePath('a.com', 'b.com'), 'sites/_compare/a.com-vs-b.com.md');
console.log('[PASS] Site comparison note builds from new and legacy captures.');
