/** Side-by-side comparison of two saved captures. Pure: reads two manifests, returns Markdown. */

type Json = Record<string, any>;

const pagesOf = (m: Json): Json[] => (Array.isArray(m.nodes) ? m.nodes : []).filter((n: Json) => n && n.kind !== 'external-domain');
const ok = (n: Json) => typeof n.statusCode === 'number' && n.statusCode >= 200 && n.statusCode < 300;
const median = (values: number[]) => {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
};
const pct = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : 'No data');
const show = (value: unknown) => (value === null || value === undefined || value === '' ? 'No data' : String(value));
const cell = (value: unknown) => show(value).replace(/\|/g, '\\|').replace(/\n/g, ' ');

export interface SiteMetrics {
  label: string;
  rows: Record<string, string>;
  topSections: string[];
  topPhrases: string[];
  schemaTypes: string[];
}

export function siteMetrics(m: Json): SiteMetrics {
  const pages = pagesOf(m);
  const good = pages.filter(ok);
  const words = good.map((n) => Number(n.wordCount) || 0);
  const thin = good.filter((n) => (Number(n.wordCount) || 0) < 200).length;
  const withSchema = good.filter((n) => Array.isArray(n.schemaTypes) && n.schemaTypes.length).length;
  const ratios = good.map((n) => Number(n.pageChecks?.textRatio)).filter(Number.isFinite).map((v) => Math.round(v * 1000) / 10);
  const flesch = good.map((n) => Number(n.pageChecks?.readability?.fleschReadingEase)).filter(Number.isFinite);
  const audit = m.audit ?? {};
  const findings: Json[] = Array.isArray(audit.findings) ? audit.findings : [];
  const byCategory = new Map<string, number>();
  for (const f of findings) byCategory.set(f.category, (byCategory.get(f.category) ?? 0) + (f.targetCount ?? f.targets?.length ?? 0));
  const intel = m.siteIntel ?? {};
  const ai = intel.aiReadiness ?? {};
  const headers = intel.techStack?.securityHeaders ?? {};
  const tls = intel.transport?.tls ?? {};
  const browserPages: Json[] = (intel.browserAudit?.pages ?? []).filter((p: Json) => !p.error);
  const lcp = median(browserPages.map((p) => Number(p.lab?.lcpMs)).filter(Number.isFinite));
  const axe = browserPages.reduce((sum, p) => sum + (p.a11y?.violations?.length ?? 0), 0);
  const thirdParty = new Set(browserPages.flatMap((p) => (p.thirdParty?.hosts ?? []).map((h: Json) => h.host)));
  const dup = audit.duplicates ?? {};
  const dupGroups = ['titles', 'descriptions', 'exactContent', 'nearContent'].reduce((sum, k) => sum + (Array.isArray(dup[k]) ? dup[k].length : 0), 0);
  const sections: Json[] = Array.isArray(m.sections) ? m.sections : [];
  const rows: Record<string, string> = {
    'Captured': show(String(m.capturedAt ?? '').slice(0, 10)),
    'Capture status': show(m.captureStatus),
    'Pages captured': String(pages.length),
    'Pages answering 2xx': String(good.length),
    'Median words per page': show(median(words)),
    'Thin pages (under 200 words)': `${thin} (${pct(thin, good.length)})`,
    'Median text to HTML ratio': ratios.length ? `${median(ratios)}%` : 'No data',
    'Median Flesch reading ease': show(median(flesch)),
    'Pages with structured data': `${withSchema} (${pct(withSchema, good.length)})`,
    'Median final request (ms)': show(m.stats?.medianResponseTimeMs),
    'Security headers present': Array.isArray(headers.present) ? String(headers.present.length) : 'No data',
    'TLS days remaining': show(tls.daysRemaining),
    'llms.txt': ai.endpoints ? (ai.endpoints.llmsTxt ? 'Present' : 'Missing') : 'No data',
    'AI crawlers allowed': ai.aiBotsPolicy ? `${ai.allowedAiBotsCount ?? 0} of ${Object.keys(ai.aiBotsPolicy).length}` : 'No data',
    'Orphan pages': show(m.stats?.orphanPages),
    'Duplicate groups': audit.duplicates ? String(dupGroups) : 'No data',
    'Internal link opportunities': Array.isArray(audit.linkOpportunities) ? String(audit.linkOpportunities.length) : 'No data',
    'Internal links to fix': Array.isArray(audit.linkFixes) ? String(audit.linkFixes.length) : 'No data',
    'Pages older than a year': audit.freshness ? String(audit.freshness.stale?.length ?? 0) : 'No data',
    'Browser sample median LCP (lab ms)': show(lcp),
    'axe rule violations in sample': browserPages.length ? String(axe) : 'No data',
    'Third-party hosts on first load': browserPages.length ? String(thirdParty.size) : 'No data',
    'External domains linked': show(m.stats?.externalDomains),
  };
  for (const category of ['pages', 'content', 'links', 'structure', 'images', 'schema', 'accessibility', 'security', 'browser']) {
    rows[`Finding items: ${category}`] = findings.length ? String(byCategory.get(category) ?? 0) : 'No data';
  }
  return {
    label: String(m.brandName || m.domain || m.siteId),
    rows,
    topSections: sections.slice(0, 6).map((s) => `${s.label} (${s.pageCount})`),
    topPhrases: (audit.keywords?.bigrams ?? []).slice(0, 8).map((k: Json) => String(k.term)),
    schemaTypes: [...new Set(good.flatMap((n) => (Array.isArray(n.schemaTypes) ? n.schemaTypes : [])))].sort() as string[],
  };
}

export function buildComparisonMarkdown(a: Json, b: Json, generatedAt = new Date().toISOString()): string {
  const left = siteMetrics(a);
  const right = siteMetrics(b);
  const onlyLeft = left.schemaTypes.filter((t) => !right.schemaTypes.includes(t));
  const onlyRight = right.schemaTypes.filter((t) => !left.schemaTypes.includes(t));
  const sharedPhrases = left.topPhrases.filter((p) => right.topPhrases.includes(p));
  const lines = [
    '---', 'tags:', '  - web-obs', '  - web-obs/compare', `generated_at: "${generatedAt}"`,
    `left: "${a.siteId}"`, `right: "${b.siteId}"`, '---', '',
    `# ${cell(left.label)} vs ${cell(right.label)}`, '',
    'Both columns come from saved captures. Captures taken on different days or with different page limits are not strictly comparable.', '',
    `| Measure | ${cell(left.label)} | ${cell(right.label)} |`, '| :--- | :--- | :--- |',
    ...Object.keys(left.rows).map((key) => `| ${key} | ${cell(left.rows[key])} | ${cell(right.rows[key])} |`), '',
    '## Largest sections', '',
    `- **${cell(left.label)}:** ${left.topSections.join(', ') || 'No data'}`,
    `- **${cell(right.label)}:** ${right.topSections.join(', ') || 'No data'}`, '',
    '## Structured data types', '',
    `- **Only ${cell(left.label)}:** ${onlyLeft.join(', ') || 'None'}`,
    `- **Only ${cell(right.label)}:** ${onlyRight.join(', ') || 'None'}`,
    `- **Both:** ${left.schemaTypes.filter((t) => right.schemaTypes.includes(t)).join(', ') || 'None'}`, '',
    '## Top phrases', '',
    `- **${cell(left.label)}:** ${left.topPhrases.join(', ') || 'No data'}`,
    `- **${cell(right.label)}:** ${right.topPhrases.join(', ') || 'No data'}`,
    `- **Shared:** ${sharedPhrases.join(', ') || 'None'}`, '',
    `Open [[sites/${a.siteId}/_dashboard|${cell(left.label)} dashboard]] or [[sites/${b.siteId}/_dashboard|${cell(right.label)} dashboard]].`, '',
  ];
  return lines.join('\n');
}

export function comparisonNotePath(a: string, b: string): string {
  return `sites/_compare/${a}-vs-${b}.md`;
}
