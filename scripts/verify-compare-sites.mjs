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
{
  // Site text is shown as text: a schema type or label cannot become HTML or an image embed.
  const hostile = structuredClone(b);
  hostile.nodes[0].schemaTypes = ['<img src="https://cdn.thirdparty.invalid/t.gif">', '![x](https://cdn.thirdparty.invalid/x.png)'];
  const note = buildComparisonMarkdown(a, hostile, '2026-11-03T00:00:00Z');
  const body = note.slice(note.indexOf('---', 3) + 3);
  assert.ok(!/<img|(?<!\\)!\[/.test(body), 'no raw HTML or image embed in the comparison note');
  assert.match(body, /&lt;img src="https:\/\/cdn\.thirdparty\.invalid\/t\.gif">/);
}
{
  // A page in a language written without spaces has no word count: not thin, not in the median.
  const cjk = structuredClone(a);
  cjk.nodes = [page('https://a.com/', 80, [], { pageChecks: { wordsMeasured: false } }), page('https://a.com/en', 500)];
  const metrics = siteMetrics(cjk);
  assert.equal(metrics.rows['Thin pages (under 200 words)'], '0 (0%)');
  assert.equal(metrics.rows['Median words per page'], '500');
  cjk.nodes = [page('https://a.com/', 80, [], { pageChecks: { wordsMeasured: false } })];
  assert.equal(siteMetrics(cjk).rows['Thin pages (under 200 words)'], 'Not measured');
}
{
  // An unreadable robots.txt leaves every bot unknown: no data, not "0 of 16".
  const unread = structuredClone(a);
  unread.siteIntel = { ...(unread.siteIntel ?? {}), aiReadiness: { ...((unread.siteIntel ?? {}).aiReadiness ?? {}),
    aiBotsPolicy: { GPTBot: 'unknown (robots fetch incomplete)', ClaudeBot: 'unknown (robots fetch incomplete)' }, allowedAiBotsCount: 0, blockedAiBots: [] } };
  assert.equal(siteMetrics(unread).rows['AI crawlers allowed'], 'No data');
  const crawlers = await build({ entryPoints: ['src/data/aiCrawlers.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  const { aiCrawlerRows, botsUnknown } = await import('data:text/javascript;base64,' + Buffer.from(crawlers.outputFiles[0].contents).toString('base64'));
  const policy = unread.siteIntel.aiReadiness.aiBotsPolicy;
  assert.equal(botsUnknown(policy), true);
  assert.deepEqual(aiCrawlerRows({ aiBotsPolicy: policy, allowedAiBotsCount: 0, blockedAiBots: [] }),
    [{ label: 'AI bots allowed at /', value: 'No data (robots.txt could not be read)' }]);
  assert.deepEqual(aiCrawlerRows({ aiBotsPolicy: { GPTBot: 'blocked', ClaudeBot: 'allowed' }, allowedAiBotsCount: 1, blockedAiBots: ['GPTBot'] }),
    [{ label: 'AI bots allowed at /', value: '1 of 2' }, { label: 'Blocked in robots.txt', value: 'GPTBot' }]);
  assert.equal(botsUnknown({ GPTBot: 'unknown (robots fetch incomplete)', ClaudeBot: 'allowed' }), false, 'a mix is still a count');
}
console.log('[PASS] Site comparison note builds from new and legacy captures, with site text kept as text, unmeasured words left out and unread robots.txt shown as no data.');
