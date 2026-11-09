import { botsUnknown } from './aiCrawlers';
import type { LlmsTxtValidation, SiteGraphManifest } from '../types/site';

export type CheckState = 'ok' | 'warn' | 'missing' | 'unknown';

export interface DiscoveryRow {
  id: string;
  label: string;
  state: CheckState;
  detail: string;
  fix?: string;
  badge?: string;
}

export interface ScoreItem {
  id: string;
  label: string;
  state: 'pass' | 'warn' | 'fail' | 'unknown';
  detail: string;
}

const LLMS_SNIPPET = '# Your Site Name\n\n> One sentence describing what the site offers.\n\n## Key pages\n- [Home](https://example.com/): what it covers\n- [Services](https://example.com/services): what it covers\n';
const SECURITY_SNIPPET = 'Contact: mailto:security@example.com\nExpires: 2027-12-31T23:59:59Z\nCanonical: https://example.com/.well-known/security.txt\n';

const SLOW_MEDIAN_MS = 800;
const VERY_SLOW_MEDIAN_MS = 1800;
const HEAVY_HTML_BYTES = 1_000_000;

/** Server-side signals only. Core Web Vitals need a real browser and are deliberately not claimed. */
function performanceScore(manifest: SiteGraphManifest): ScoreItem {
  const nodes = manifest.nodes ?? [];
  const times = nodes.map((n) => n.responseTimeMs).filter((t): t is number => typeof t === 'number' && t > 0).sort((a, b) => a - b);
  const compression = manifest.siteIntel?.techStack?.httpCompression;
  const heavy = nodes.filter((n) => (n.htmlBytes ?? 0) > HEAVY_HTML_BYTES).length;
  if (times.length === 0 && compression === undefined) {
    return { id: 'performance', label: 'Performance', state: 'unknown', detail: 'No timing data. Core Web Vitals are not assessed by Web-Obs.' };
  }
  const median = times.length ? times[Math.floor(times.length / 2)] : null;
  const notes: string[] = [];
  if (median !== null) notes.push(`median response ${median} ms`);
  if (compression !== undefined) notes.push(compression ? `homepage compressed (${compression})` : 'homepage not compressed');
  if (heavy > 0) notes.push(`${heavy} page${heavy === 1 ? '' : 's'} over 1 MB of HTML`);
  const state: ScoreItem['state'] =
    median !== null && median > VERY_SLOW_MEDIAN_MS
      ? 'fail'
      : (median !== null && median > SLOW_MEDIAN_MS) || compression === null || heavy > 0
        ? 'warn'
        : 'pass';
  return { id: 'performance', label: 'Performance', state, detail: `${notes.join('; ')}. Server signals only, not Core Web Vitals.` };
}

type AiIntel = NonNullable<NonNullable<SiteGraphManifest['siteIntel']>['aiReadiness']>;
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;

/** llms.txt against the llmstxt.org format, with its links checked against the capture. */
export function llmsRow(ai: AiIntel, llms: LlmsTxtValidation | undefined): DiscoveryRow {
  const probe = ai.llmsProbe?.llmsTxt;
  const draft = ai.llmsDraft?.text;
  const fix = draft || LLMS_SNIPPET;
  if (!ai.endpoints.llmsTxt) {
    // Optional: Google Search ignores it and Lighthouse marks a 404 as not applicable. Only a server error is a problem.
    const serverError = probe?.state === 'unavailable' && (probe.statusCode ?? 0) >= 500;
    const detail = serverError ? `The server fails with HTTP ${probe.statusCode} when asked for it.`
      : probe?.state === 'html' ? 'The address serves a web page instead of a markdown file.'
      : probe?.state === 'refused' ? 'Not checked: robots.txt does not allow fetching it.'
      : probe?.state === 'unavailable' ? `Not checked: the site answered ${probe.detail ?? 'with an error'}`
      : probe?.state === 'not-checked' ? `Not checked. ${probe.detail ?? ''}`.trim()
      : 'Not found.';
    const answered = !probe || probe.state === 'absent' || probe.state === 'html';
    const note = answered ? ' Optional: Google Search ignores it; coding tools and assistants given your site can use it.' : '';
    return { id: 'llms', label: 'llms.txt', state: serverError ? 'warn' : 'unknown',
      detail: detail + note + (draft && answered ? ' A draft built from this capture is ready to copy.' : ''),
      fix: answered || serverError ? fix : undefined };
  }
  if (!llms?.notes) {  // captured before 0.2.0 checked the full format
    return { id: 'llms', label: 'llms.txt', state: llms?.issues.length ? 'warn' : 'ok',
      detail: llms?.issues.length ? `Found. Check: ${llms.issues.join(', ')}.` : 'Found and matches the llmstxt.org format.',
      fix: llms && !llms.valid ? fix : undefined };
  }
  const notes = llms.notes;
  const errors = notes.filter(n => n.level === 'error').length;
  const warnings = notes.filter(n => n.level === 'warn').length;
  const links = ai.llmsLinks ?? [];
  const dead = links.filter(l => l.state === 'broken' || l.state === 'unavailable' || l.state === 'blocked').length;
  const loose = links.filter(l => l.state === 'redirect' || l.state === 'noindex' || l.state === 'non-canonical').length;
  const parts = [`Found: ${plural(llms.stats?.sections ?? 0, 'section')}, ${plural(llms.stats?.links ?? 0, 'link')}${llms.hasOptional ? ', an Optional section' : ''}.`];
  if (errors) parts.push(`${plural(errors, 'format error')}.`);
  if (warnings) parts.push(`${plural(warnings, 'format note')}.`);
  if (dead) parts.push(`${plural(dead, 'link')} agents cannot use.`);
  if (loose) parts.push(`${plural(loose, 'link')} could be more direct.`);
  const sameSite = links.filter(l => l.sameSite);
  if (!errors && !warnings) parts.push('Matches the llmstxt.org format.');
  if (sameSite.length && sameSite.every(l => l.state === 'ok')) parts.push(`All ${plural(sameSite.length, 'link')} on this site work.`);
  const unchecked = sameSite.filter(l => l.state === 'unchecked').length;
  if (unchecked) parts.push(`${plural(unchecked, 'link')} on this site not checked.`);
  return {
    id: 'llms', label: 'llms.txt',
    state: errors || warnings || dead || loose ? 'warn' : 'ok',
    detail: parts.join(' '),
    fix: errors ? fix : undefined,
    badge: llms.stats ? `~${llms.stats.approxTokens.toLocaleString('en-US')} tokens` : undefined,
  };
}

/** llms.txt v2: pages that declare a markdown copy, and whether the copies checked load as markdown. */
export function markdownRow(ai: AiIntel): DiscoveryRow | null {
  const info = ai.markdownAlternates;
  if (!info) return null;
  const checked = info.checked.filter(r => r.state !== 'unchecked' && r.state !== 'blocked');
  const bad = checked.filter(r => r.state !== 'ok');
  if (!info.declaredPages) {
    return { id: 'markdown-copies', label: 'Markdown page copies', state: 'unknown',
      detail: 'No page declares a markdown copy. Optional (llms.txt v2): rel="alternate" type="text/markdown".' };
  }
  return { id: 'markdown-copies', label: 'Markdown page copies', state: bad.length ? 'warn' : 'ok',
    detail: `${plural(info.declaredPages, 'page')} declare a markdown copy. ` + (checked.length
      ? (bad.length ? `${bad.length} of ${checked.length} checked do not load as markdown.` : `All ${checked.length} checked load as markdown.`)
      : 'None could be checked.') };
}

export function buildDiscoveryChecklist(manifest: SiteGraphManifest): { rows: DiscoveryRow[]; score: ScoreItem[] } {
  const ai = manifest.siteIntel?.aiReadiness;
  const robots = manifest.robotsPolicy;
  const rows: DiscoveryRow[] = [];
  const v = (key: string) => ai?.validation?.[key];

  rows.push(
    robots
      ? {
          id: 'robots',
          label: 'robots.txt',
          state: robots.state === 'parsed' ? 'ok' : robots.canCrawl ? 'warn' : 'unknown',
          detail: robots.reason,
          fix: robots.state === 'parsed' ? undefined : 'Publish /robots.txt with a Sitemap line and explicit AI crawler rules.',
        }
      : { id: 'robots', label: 'robots.txt', state: 'unknown', detail: 'Not recorded in this capture.' },
  );

  const sitemapCount = manifest.sitemaps?.length ?? 0;
  const hygiene = ai?.sitemapHygiene;
  const undeclared = hygiene?.undeclaredSitemaps.length ?? 0;
  rows.push({
    id: 'sitemap',
    label: 'XML sitemap',
    state: sitemapCount === 0 ? 'missing' : undeclared > 0 ? 'warn' : 'ok',
    detail:
      sitemapCount === 0
        ? 'No sitemap found in robots.txt or at common paths.'
        : `${sitemapCount} found, ${manifest.stats.sitemapUrlsTotal} URLs.${undeclared ? ` ${undeclared} not declared in robots.txt.` : ''}`,
    fix: sitemapCount === 0 || undeclared > 0 ? 'Add "Sitemap: https://your-domain/sitemap.xml" to robots.txt.' : undefined,
  });

  if (ai) {
    rows.push(llmsRow(ai, v('llmsTxt')));
    const markdown = markdownRow(ai);
    if (markdown) rows.push(markdown);
    rows.push({
      id: 'llms-full',
      label: 'llms-full.txt',
      state: ai.endpoints.llmsFullTxt ? 'ok' : 'unknown',
      detail: ai.endpoints.llmsFullTxt ? 'Found. A common convention, not part of the llms.txt spec.' : 'Not found. Optional convention, not part of the spec.',
    });
    rows.push({ id: 'ai-catalog', label: 'ai-catalog.json', state: ai.endpoints.aiCatalogJson ? 'ok' : 'unknown', detail: ai.endpoints.aiCatalogJson ? 'Found.' : 'Not found. Optional.' });
    rows.push({
      id: 'api-catalog',
      label: 'api-catalog (RFC 9727)',
      state: ai.endpoints.apiCatalog ? 'ok' : 'unknown',
      detail: ai.endpoints.apiCatalog ? 'Found.' : 'Not found. Only relevant if the site publishes public APIs.',
    });
    rows.push({
      id: 'agent',
      label: 'agent.json / mcp.json',
      state: ai.endpoints.agentJson || ai.endpoints.mcpJson ? 'ok' : 'unknown',
      detail: ai.endpoints.agentJson || ai.endpoints.mcpJson ? 'Found.' : 'Not found. Optional.',
    });
    const sec = v('securityTxt');
    rows.push({
      id: 'security',
      label: 'security.txt',
      state: !ai.endpoints.securityTxt ? 'missing' : sec && !sec.valid ? 'warn' : 'ok',
      detail: !ai.endpoints.securityTxt ? 'Not found at /.well-known/security.txt.' : sec && !sec.valid ? `Found. Check: ${sec.issues.join(', ')}.` : `Found. Expires ${sec?.expires?.slice(0, 10) ?? 'unknown'}.`,
      fix: !ai.endpoints.securityTxt || (sec && !sec.valid) ? SECURITY_SNIPPET : undefined,
    });
    rows.push({ id: 'humans', label: 'humans.txt', state: ai.endpoints.humansTxt ? 'ok' : 'unknown', detail: ai.endpoints.humansTxt ? 'Found.' : 'Not found. Optional.' });
    rows.push({ id: 'manifest', label: 'manifest.webmanifest', state: ai.endpoints.webManifest ? 'ok' : 'unknown', detail: ai.endpoints.webManifest ? 'Found.' : 'Not found at the default path. Sites may link a manifest elsewhere.' });
    const rf = ai.robotsFindings;
    if (rf) {
      const notes = [rf.blanketDisallow && 'blocks all crawling', rf.blocksAssets.length > 0 && `blocks assets (${rf.blocksAssets.slice(0, 3).join(', ')})`, !rf.hasSitemapLine && 'no Sitemap line', rf.contentSignal && `Content-Signal: ${rf.contentSignal}`].filter(Boolean);
      rows.push({
        id: 'robots-findings',
        badge: rf.blanketDisallow || rf.blocksAssets.length > 0 || !rf.hasSitemapLine ? 'Check' : 'Pass',
        label: 'robots.txt review',
        state: rf.blanketDisallow || rf.blocksAssets.length > 0 || !rf.hasSitemapLine ? 'warn' : 'ok',
        detail: notes.length ? notes.join('; ') + '.' : 'No blanket block, no blocked assets, Sitemap line present.',
      });
    }
    const labels: Record<string, string> = { httpToHttps: 'HTTP to HTTPS', alternateHost: 'www / non-www', soft404: 'Unknown URL response' };
    for (const [key, check] of Object.entries(ai.siteChecks ?? {})) {
      rows.push({
        id: `site-${key}`,
        badge: check.state === 'ok' ? 'Pass' : check.state === 'fail' || check.state === 'warn' ? 'Check' : 'Not checked',
        label: labels[key] ?? key,
        state: check.state === 'ok' ? 'ok' : check.state === 'fail' || check.state === 'warn' ? 'warn' : 'unknown',
        detail: check.detail,
      });
    }
    rows.push({
      id: 'indexnow',
      badge: 'Not detectable',
      label: 'IndexNow',
      state: 'unknown',
      detail: 'The key file name is private to each site, so it cannot be detected from outside. Check your CMS or Bing Webmaster Tools.',
    });
    rows.push({ id: 'ads', label: 'ads.txt', state: ai.endpoints.adsTxt ? 'ok' : 'unknown', detail: ai.endpoints.adsTxt ? 'Found.' : 'Not found. Only needed for sites that sell ads.' });
  }

  const nodes = manifest.nodes ?? [];
  const pages = nodes.filter((n) => n.seoIssues !== undefined);
  const noindexPages = pages.filter((n) => n.seoIssues?.some((i) => i.startsWith('noindex'))).length;
  const noCanonical = pages.filter((n) => n.seoIssues?.includes('missing-canonical')).length;
  const lh = manifest.linkHealth;
  const hygieneIssues = hygiene ? hygiene.broken.length + hygiene.unavailable.length + hygiene.redirect.length + hygiene.noindex.length : 0;
  const redirectFail = Object.values(ai?.siteChecks ?? {}).some((c) => c.state === 'fail');
  const headers = manifest.siteIntel?.techStack?.securityHeaders;
  const blocked = ai?.blockedAiBots.length ?? 0;
  // When robots.txt could not be read every bot is "unknown": that is no data, never a pass.
  const aiBotsUnknown = botsUnknown(ai?.aiBotsPolicy);

  const score: ScoreItem[] = [
    {
      id: 'crawlability',
      label: 'Crawlability',
      state: !robots ? 'unknown' : !robots.canCrawl || ai?.robotsFindings?.blanketDisallow ? 'fail' : sitemapCount === 0 || (ai?.robotsFindings?.blocksAssets.length ?? 0) > 0 ? 'warn' : 'pass',
      detail: !robots ? 'No robots data.' : !robots.canCrawl ? robots.reason : sitemapCount === 0 ? 'Crawlable, but no sitemap found.' : 'Crawlable with a sitemap.',
    },
    {
      id: 'indexability',
      label: 'Indexability',
      state: pages.length === 0 ? 'unknown' : noindexPages > 0 || noCanonical > 0 || hygieneIssues > 0 ? 'warn' : 'pass',
      detail: pages.length === 0 ? 'No page data.' : `${noindexPages} noindex, ${noCanonical} without canonical, ${hygieneIssues} problem URLs in sitemaps.`,
    },
    {
      id: 'ai',
      label: 'AI readiness',
      // A missing llms.txt is optional and does not lower this score; an invalid one does.
      state: !ai ? 'unknown' : blocked > 0 || (v('llmsTxt') && !v('llmsTxt')!.valid) ? 'warn' : aiBotsUnknown ? 'unknown' : 'pass',
      detail: !ai ? 'No data.' : `llms.txt ${ai.endpoints.llmsTxt ? 'present' : 'missing'}; `
        + (aiBotsUnknown ? 'AI crawler access unknown: robots.txt could not be read.' : `${blocked} AI bots blocked in robots.txt.`),
    },
    {
      id: 'security',
      label: 'Security',
      state: !headers ? 'unknown' : headers.missing.length > 3 || redirectFail ? 'fail' : headers.missing.length > 0 || (headers.consistency?.inconsistent.length ?? 0) > 0 || (ai && !ai.endpoints.securityTxt) ? 'warn' : 'pass',
      detail: !headers ? 'No header data.' : `${headers.missing.length} homepage security headers missing${(headers.consistency?.inconsistent.length ?? 0) > 0 ? `; ${headers.consistency!.inconsistent.length} inconsistent across ${headers.consistency!.sampledPages} sampled pages` : ''}${ai && !ai.endpoints.securityTxt ? '; no security.txt' : ''}.`,
    },
    {
      id: 'links',
      label: 'Links',
      state: !lh ? 'unknown' : lh.brokenLinks.length > 0 ? 'fail' : lh.serverErrors.length > 0 || lh.uncheckedCount > 0 ? 'warn' : 'pass',
      detail: !lh ? 'No link data.' : `${lh.brokenLinks.length} broken, ${lh.serverErrors.length} server errors, ${lh.uncheckedCount} unchecked.`,
    },
    performanceScore(manifest),
  ];

  return { rows, score };
}
