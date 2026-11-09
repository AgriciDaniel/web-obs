import type { SiteGraphManifest, SiteNode, SiteResource } from '../types/site';
import { pendingLinkChecks } from './linkCoverage';

export type AuditCategory = 'pages' | 'content' | 'links' | 'structure' | 'images' | 'schema' | 'accessibility' | 'headers' | 'security' | 'browser' | 'changes';
export type AuditTone = 'good' | 'attention' | 'review' | 'coverage' | 'neutral';
export interface AuditBucket { id: string; label: string; count: number; tone: AuditTone }
export interface AuditTarget { id: string; label: string; url: string; detail: string; pageId?: string; notePath?: string; sourcePageId?: string }
export interface AuditFinding {
  id: string;
  category: AuditCategory;
  tone: 'attention' | 'review' | 'coverage';
  title: string;
  explanation: string;
  targets: AuditTarget[];
  /** Total affected items when the engine stored only the first 200 targets. */
  totalTargets?: number;
}
export const AUDIT_CATEGORIES: Array<{ id: AuditCategory; label: string }> = [
  { id: 'pages', label: 'Page signals' }, { id: 'content', label: 'Content' }, { id: 'links', label: 'Links' },
  { id: 'structure', label: 'Site structure' }, { id: 'images', label: 'Images' }, { id: 'schema', label: 'Structured data' },
  { id: 'accessibility', label: 'Accessibility' }, { id: 'headers', label: 'Response headers' }, { id: 'security', label: 'Security' },
  { id: 'browser', label: 'Browser sample' }, { id: 'changes', label: 'Changes' },
];
const CATEGORY_IDS = new Set<string>(AUDIT_CATEGORIES.map(category => category.id));
export const AUDIT_NOT_ASSESSED = ['Core Web Vitals field data', 'Full accessibility conformance', 'E-E-A-T judgement', 'Cookie consent', 'Legal compliance'];
/** Why each area stays unassessed, shown beside the list. */
export const AUDIT_SCOPE_NOTES = [
  'Lab timings come from one sampled browser load on this machine, not from real visitors.',
  'axe-core runs automated rules on a few sampled pages. Automated rules cover only part of WCAG, so manual review is still needed.',
  'Trust pages, bylines and dates are recorded as present or absent. Their quality is not judged.',
  'Third-party requests and cookies are observed on first load with no interaction. That is not a consent or legal assessment.',
];
const validCount = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const titleCase = (value: string) => value.replace(/-/g, ' ').replace(/^./, letter => letter.toUpperCase());
const urlKey = (url: string) => url.replace(/#.*$/, '').replace(/\/+$/, '').toLowerCase();
const pageTarget = (page: SiteNode, detail = ''): AuditTarget => ({ id: page.id, label: page.title || page.path, url: page.url, detail, pageId: page.id, notePath: page.obsidianPath });

function mediaState(resource: SiteResource): string {
  if (resource.localPath) return 'saved';
  if (resource.downloadState === 'not-selected' || resource.downloadState === 'not-requested') return 'intentional';
  if (resource.downloadState === 'unavailable') return 'unavailable';
  if (resource.downloadState === 'budget-skipped' || resource.downloadState === 'deadline-skipped') return 'budget';
  if (resource.downloadState === 'reference' || !resource.downloadState) return 'reference';
  return 'other';
}

/** Summarize saved observations only. This function makes no requests and does not run audit rules. */
export function buildSiteAudit(manifest: SiteGraphManifest) {
  const pages = manifest.nodes.filter(node => node.kind !== 'external-domain');
  const pageByUrl = new Map(pages.map(page => [page.url, page]));
  const pageById = new Map(pages.map(page => [page.id, page]));
  const findings = new Map<string, AuditFinding>();
  const findingTargets = new Map<string, Set<string>>();
  const add = (id: string, category: AuditCategory, tone: AuditFinding['tone'], title: string, explanation: string, target: AuditTarget) => {
    const finding = findings.get(id) ?? { id, category, tone, title, explanation, targets: [] };
    const seen = findingTargets.get(id) ?? new Set<string>();
    if (!seen.has(target.id)) { finding.targets.push(target); seen.add(target.id); }
    findingTargets.set(id, seen);
    findings.set(id, finding);
  };
  const catalog = manifest.issueCatalog ?? {};
  const engineFindings = Array.isArray(manifest.audit?.findings) ? manifest.audit.findings : null;
  const pageByKey = new Map(pages.map(page => [urlKey(page.url), page]));
  const findPage = (url?: string) => url ? pageByUrl.get(url) ?? pageByKey.get(urlKey(url)) : undefined;
  const totals = new Map<string, number>();
  if (engineFindings) {
    for (const finding of engineFindings) {
      const category = (CATEGORY_IDS.has(finding.category) ? finding.category : 'pages') as AuditCategory;
      for (const raw of finding.targets) {
        const page = findPage(raw.url);
        const source = findPage(raw.sourceUrl);
        const detail = raw.detail ?? '';
        const id = `${raw.url}|${raw.sourceUrl ?? ''}|${detail}`;
        const target: AuditTarget = page
          ? { ...pageTarget(page, detail), id }
          : { id, label: raw.url, url: raw.url, detail, sourcePageId: source?.id, notePath: source?.obsidianPath };
        if (page && source && source.id !== page.id) target.sourcePageId = source.id;
        add(finding.id, category, finding.tone, finding.title, finding.explanation, target);
      }
      if (typeof finding.targetCount === 'number' && finding.targetCount > finding.targets.length) totals.set(finding.id, finding.targetCount);
    }
  }
  const sections = new Map<string, number>();
  let imageMetricPages = 0, imagesObserved = 0, imagesMissingAlt = 0;
  for (const page of pages) {
    sections.set(page.section || 'root', (sections.get(page.section || 'root') ?? 0) + 1);
    if (engineFindings) {
      // The engine already reports page issues as findings; only collect image totals here.
      if (validCount(page.imagesMissingAlt) && page.statusCode >= 200 && page.statusCode < 400 && page.health !== 'unavailable') {
        imageMetricPages += 1;
        imagesObserved += validCount(page.imagesCount) ? page.imagesCount : 0;
        imagesMissingAlt += page.imagesMissingAlt;
      }
      continue;
    }
    if (page.health === 'broken') add('page-broken', 'pages', 'attention', 'Pages returned an error', 'The saved page response was marked broken. Inspect the recorded status and source before changing a URL.', pageTarget(page, `HTTP ${page.statusCode || 'not recorded'}`));
    if (page.health === 'unavailable') add('page-unavailable', 'pages', 'coverage', 'Page content was unavailable', 'The capture could not collect usable page content. This is a collection gap, not proof that the page is permanently broken.', pageTarget(page));
    if (page.health === 'redirect') add('page-redirect', 'pages', 'review', 'Redirected pages', 'A redirect was recorded. Check whether the redirect is intentional and whether internal links should use its destination.', pageTarget(page));
    if (page.health === 'orphan') add('orphan', 'structure', 'review', 'Pages not reached from the captured homepage', 'No route from the captured homepage was recorded. Links within disconnected page groups may still exist, and uncaptured pages may add routes.', pageTarget(page));
    if (page.health === 'unlisted') add('unlisted', 'structure', 'review', 'Pages absent from the discovered sitemap', 'These pages were reached during capture but were not in the discovered sitemap inventory. Exclusion can be intentional.', pageTarget(page));
    for (const issue of new Set(page.seoIssues ?? [])) {
      if ((issue === 'page-broken' && page.health === 'broken') || (issue === 'page-unavailable' && page.health === 'unavailable') || (issue === 'orphan-page' && page.health === 'orphan') || (issue === 'unlisted-in-sitemap' && page.health === 'unlisted') || (issue === 'redirected-source-url' && page.health === 'redirect')) continue;
      if (issue.startsWith('images-missing-alt') && validCount(page.imagesMissingAlt)) continue;
      const slug = issue.replace(/\s*\(\d+\)$/, '');
      const entry = catalog[slug];
      const category = (entry && CATEGORY_IDS.has(entry.category) ? entry.category : 'pages') as AuditCategory;
      add(`seo:${slug}`, category, entry?.tone ?? 'review', entry?.title ?? titleCase(slug), entry?.explanation ?? 'A signal recorded by the capture. Review it in the page context; a flag does not establish a ranking, accessibility, or content quality failure.', pageTarget(page, issue));
    }
    if (validCount(page.imagesMissingAlt) && page.statusCode >= 200 && page.statusCode < 400 && page.health !== 'unavailable') {
      imageMetricPages += 1;
      imagesObserved += validCount(page.imagesCount) ? page.imagesCount : 0;
      imagesMissingAlt += page.imagesMissingAlt;
      if (page.imagesMissingAlt > 0) add('missing-alt', 'images', 'review', 'Images recorded without alt text', 'Review the image purpose before writing text. Decorative images may correctly use an empty alternative. This is not a complete accessibility assessment.', pageTarget(page, `${page.imagesMissingAlt} image${page.imagesMissingAlt === 1 ? '' : 's'} recorded without alt text`));
    }
  }
  const pageSections: AuditBucket[] = [...sections].map(([id, count]) => ({ id, label: id === 'root' ? '/' : id, count, tone: 'neutral' as const })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  const linkDefinitions: Array<Omit<AuditBucket, 'count'>> = [
    { id: 'ok', label: 'Responded OK', tone: 'good' }, { id: 'broken', label: '404 / 410', tone: 'attention' },
    { id: 'server-error', label: 'Server error', tone: 'review' }, { id: 'unknown', label: 'Inconclusive', tone: 'coverage' },
    { id: 'unchecked', label: 'Unchecked', tone: 'neutral' }, { id: 'unrecorded', label: 'No saved result', tone: 'neutral' },
  ];
  const links = new Map((manifest.linkHealth?.results ?? []).map(row => [row.url, row]));
  const linkCounts = new Map<string, number>();
  const resources = manifest.resources ?? [];
  const linkSources = new Map<string, string>();
  for (const resource of resources) {
    const source = resource.references.map(reference => pageByUrl.get(reference.pageUrl)).find(Boolean);
    if (source) linkSources.set(resource.url, source.id);
  }
  for (const edge of manifest.edges) {
    if (edge.targetUrl && pageById.has(edge.source) && !linkSources.has(edge.targetUrl)) linkSources.set(edge.targetUrl, edge.source);
  }
  for (const row of links.values()) {
    const needsConfirmation = row.status === 'broken' && row.method === 'HEAD';
    const status = needsConfirmation ? 'unknown' : row.statusCode === 404 || row.statusCode === 410 ? 'broken' : row.status === 'broken' ? 'unknown' : row.status;
    linkCounts.set(status, (linkCounts.get(status) ?? 0) + 1);
    if (status === 'ok') continue;
    const page = pageByUrl.get(row.url);
    const detail = needsConfirmation ? `${row.reason} HEAD only; GET confirmation is still required.` : row.reason;
    const target: AuditTarget = page ? pageTarget(page, detail) : { id: row.url, label: row.url, url: row.url, detail, sourcePageId: linkSources.get(row.url) };
    if (status === 'broken') add('link-broken', 'links', 'attention', 'Destinations returned 404 or 410', 'A direct check returned a missing or gone response. Confirm the destination and update the referring link where appropriate.', target);
    if (status === 'server-error') add('link-server', 'links', 'review', 'Destinations returned server errors', 'The destination returned a server error at check time. This can be temporary; retry before treating it as a permanent failure.', target);
    if (status === 'unknown') add('link-unknown', 'links', 'coverage', 'Destination checks were inconclusive', 'Blocking, throttling, and transport failures do not prove a broken link. The saved reason explains what the check could establish.', target);
    if (status === 'unchecked') add('link-unchecked', 'links', 'coverage', 'Destinations have not been checked', 'These observed targets were not attempted. They contribute no evidence of a working or broken destination.', target);
  }
  const linkTotal = Math.max(links.size, manifest.linkHealth?.totalCount ?? 0);
  linkCounts.set('unrecorded', linkTotal - links.size);
  const linkDistribution = linkDefinitions.map(bucket => ({ ...bucket, count: linkCounts.get(bucket.id) ?? 0 }));
  const mediaDefinitions: Array<Omit<AuditBucket, 'count'>> = [
    { id: 'saved', label: 'Saved locally', tone: 'good' }, { id: 'reference', label: 'Reference only', tone: 'neutral' },
    { id: 'intentional', label: 'Intentionally not selected', tone: 'neutral' }, { id: 'budget', label: 'Skipped by budget', tone: 'coverage' },
    { id: 'unavailable', label: 'Unavailable', tone: 'attention' }, { id: 'other', label: 'Other recorded state', tone: 'review' },
  ];
  const mediaCounts = new Map<string, number>(), typeCounts = new Map<string, number>();
  for (const resource of resources) {
    const state = mediaState(resource);
    mediaCounts.set(state, (mediaCounts.get(state) ?? 0) + 1);
    typeCounts.set(resource.type, (typeCounts.get(resource.type) ?? 0) + 1);
  }
  const mediaDistribution = mediaDefinitions.map(bucket => ({ ...bucket, count: mediaCounts.get(bucket.id) ?? 0 }));
  const mediaTypes = [...typeCounts].map(([id, count]) => ({ id, label: titleCase(id), count, tone: 'neutral' as const })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  const headers = manifest.siteIntel?.techStack?.securityHeaders;
  const home = pages.find(page => page.kind === 'home');
  const headerScope = manifest.siteIntel?.techStack?.coverage?.securityHeadersScope || 'Saved homepage response. Legacy scope details were not recorded.';
  if (home && headers?.missing.length) add('headers-missing', 'headers', 'review', 'Response headers were not observed', `${headers.missing.join(', ')}. Scope: ${headerScope} Presence alone does not establish a secure configuration.`, pageTarget(home));
  const order = { attention: 0, review: 1, coverage: 2 };
  for (const [id, total] of totals) { const group = findings.get(id); if (group && total > group.targets.length) group.totalTargets = total; }
  const size = (group: AuditFinding) => group.totalTargets ?? group.targets.length;
  const groups = [...findings.values()].sort((a, b) => order[a.tone] - order[b.tone] || size(b) - size(a) || a.title.localeCompare(b.title));
  const data = manifest.audit;
  const duplicateGroups = data?.duplicates ? data.duplicates.titles.length + data.duplicates.descriptions.length + data.duplicates.exactContent.length + data.duplicates.nearContent.length : null;
  return {
    engineFindings: engineFindings !== null,
    extras: data ? {
      linkOpportunities: data.linkOpportunities?.length ?? null,
      linkFixes: data.linkFixes?.length ?? null,
      duplicateGroups,
      tasks: data.tasks ?? null,
    } : null,
    scopeNotes: AUDIT_SCOPE_NOTES,
    pageCount: pages.length, pagesWithFindings: new Set(groups.flatMap(group => group.targets.flatMap(target => target.pageId ? [target.pageId] : []))).size,
    findings: groups, findingCount: groups.reduce((sum, group) => sum + size(group), 0),
    pageSections, linkDistribution, linkTotal, linkAttempted: manifest.linkHealth?.checkedCount ?? null,
    linksObserved: manifest.linkHealth !== undefined, linkUnchecked: linkCounts.get('unchecked') ?? 0, linkPending: pendingLinkChecks(manifest.linkHealth),
    mediaDistribution, mediaTypes, resourceCount: resources.length, mediaObserved: manifest.resources !== undefined,
    imageMetricPages, imagesObserved, imagesMissingAlt,
    headers: headers ? { present: [...headers.present], missing: [...headers.missing], scope: headerScope } : null,
    notAssessed: AUDIT_NOT_ASSESSED,
  };
}

export type SiteAudit = ReturnType<typeof buildSiteAudit>;

export function filterAuditFindings(findings: AuditFinding[], category: AuditCategory | 'all', query: string): AuditFinding[] {
  const needle = query.trim().toLocaleLowerCase();
  return findings.flatMap(group => {
    if (category !== 'all' && group.category !== category) return [];
    if (!needle || `${group.title} ${group.explanation}`.toLocaleLowerCase().includes(needle)) return [group];
    const targets = group.targets.filter(target => `${target.label} ${target.url} ${target.detail}`.toLocaleLowerCase().includes(needle));
    return targets.length ? [{ ...group, targets, totalTargets: undefined }] : [];
  });
}
