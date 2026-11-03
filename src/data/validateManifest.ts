import type { SiteGraphManifest } from '../types/site';

type ObjectValue = Record<string, unknown>;
const object = (value: unknown): value is ObjectValue => value !== null && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((entry) => typeof entry === 'string');
const count = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const optionalText = (value: unknown): boolean => value === undefined || value === null || typeof value === 'string';

export function isSafeSiteId(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 180 && /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(value);
}

/** Validate persisted data before it reaches React or the Three.js layout. */
export function parseSiteManifest(value: unknown): SiteGraphManifest {
  const fail = (part: string): never => { throw new Error(`Invalid site capture: ${part}. Re-capture the site or restore a valid snapshot.`); };
  if (!object(value)) return fail('expected a manifest object');
  if (typeof value.schemaVersion !== 'string' || !/^1\.\d+\.\d+$/.test(value.schemaVersion)) return fail('unsupported schema version');
  if (!isSafeSiteId(value.siteId) || typeof value.domain !== 'string' || !value.domain || typeof value.origin !== 'string' || !/^https?:\/\//i.test(value.origin)) return fail('invalid site identity');
  if (typeof value.capturedAt !== 'string' || !Number.isFinite(Date.parse(value.capturedAt)) || !count(value.elapsedSec)) return fail('invalid capture date or duration');
  if (value.captureStatus !== undefined && !['complete', 'partial'].includes(String(value.captureStatus))) return fail('invalid capture status');
  if (value.preservationStatus !== undefined && value.preservationStatus !== 'conflicts') return fail('invalid preservation status');
  if (value.captureWarnings !== undefined && !strings(value.captureWarnings)) return fail('invalid coverage warnings');
  if (value.captureProvenance !== undefined) {
    const provenance = value.captureProvenance;
    if (!object(provenance) || typeof provenance.engineSha256 !== 'string' || !object(provenance.configuration) || !object(provenance.runtime) || typeof provenance.runtime.pythonVersion !== 'string' || typeof provenance.runtime.platform !== 'string') return fail('invalid capture provenance');
    if (provenance.runtime.pythonExecutable !== undefined && typeof provenance.runtime.pythonExecutable !== 'string') return fail('invalid capture runtime');
    if (provenance.runtime.packages !== undefined && (!object(provenance.runtime.packages) || Object.values(provenance.runtime.packages).some((entry) => entry !== null && typeof entry !== 'string'))) return fail('invalid capture runtime');
    if (provenance.engineFiles !== undefined && (!object(provenance.engineFiles) || Object.values(provenance.engineFiles).some((entry) => typeof entry !== 'string'))) return fail('invalid capture engine files');
    if (provenance.browserEvidence !== undefined && typeof provenance.browserEvidence !== 'string') return fail('invalid capture browser evidence');
  }
  const stats = value.stats;
  const statNames = ['pagesCrawled', 'sitemapsFound', 'sitemapUrlsTotal', 'internalEdges', 'externalDomains', 'externalEdges', 'localImagesDownloaded', 'orphanPages', 'unlistedPages', 'brokenOrRedirectPages'];
  if (!object(stats) || statNames.some((key) => !count(stats[key]))) return fail('invalid capture totals');
  for (const key of ['pagesWithSeoIssues', 'avgResponseTimeMs']) if (stats[key] !== undefined && !count(stats[key])) return fail(`invalid ${key}`);
  if (!Array.isArray(value.nodes) || value.nodes.length > 20000 || !Array.isArray(value.edges) || value.edges.length > 200000) return fail('invalid graph inventory');
  const nodeIds = new Set<string>();
  for (const node of value.nodes) {
    if (!object(node) || typeof node.id !== 'string' || !node.id || nodeIds.has(node.id)) return fail('invalid or duplicate node ID');
    nodeIds.add(node.id);
    if (!['home', 'hub', 'page', 'external-domain'].includes(String(node.kind)) || !['home', 'hub', 'healthy', 'orphan', 'unlisted', 'redirect', 'broken', 'unavailable', 'external'].includes(String(node.health))) return fail('invalid node type');
    if (['title', 'url', 'path', 'section', 'obsidianPath', 'metaDescription', 'canonical', 'metaRobots'].some((key) => typeof node[key] !== 'string')) return fail('invalid page text fields');
    if (!strings(node.h1) || !strings(node.schemaTypes) || typeof node.inSitemap !== 'boolean' || typeof node.renderUsed !== 'boolean') return fail('invalid page metadata');
    if (['statusCode', 'urlDepth', 'wordCount', 'h2Count', 'imagesCount', 'localImagesCount', 'inlinksBody', 'inlinksTotal', 'outlinksBody', 'outlinksTotal', 'externalDomainsOut'].some((key) => !count(node[key])) || (node.clickDepth !== null && !count(node.clickDepth))) return fail('invalid page metrics');
    if (node.authorityScore !== undefined && (!count(node.authorityScore) || node.authorityScore > 100)) return fail('invalid relative link score');
    if (node.noteStatus !== undefined && node.noteStatus !== 'preserved-local-edits') return fail('invalid note status');
    for (const key of ['seoIssues', 'externalUrlsSample']) if (node[key] !== undefined && !strings(node[key])) return fail(`invalid ${key}`);
  }
  const edgeIds = new Set<string>();
  for (const edge of value.edges) {
    if (!object(edge) || typeof edge.id !== 'string' || edgeIds.has(edge.id) || !nodeIds.has(String(edge.source)) || !nodeIds.has(String(edge.target)) || !['sitemap-hierarchy', 'internal-body', 'internal-chrome', 'external'].includes(String(edge.kind))) return fail('invalid graph edge');
    edgeIds.add(edge.id);
  }
  if (!Array.isArray(value.sections) || value.sections.some((section) => !object(section) || typeof section.id !== 'string' || typeof section.label !== 'string' || !count(section.pageCount))) return fail('invalid sections');
  if (!Array.isArray(value.sitemaps) || value.sitemaps.some((entry) => !object(entry) || typeof entry.url !== 'string' || typeof entry.kind !== 'string')) return fail('invalid sitemaps');
  if (value.linkHealth !== undefined) {
    const links = value.linkHealth;
    if (!object(links) || ['totalCount', 'checkedCount', 'uncheckedCount', 'unknownCount', 'assessedCount'].some((key) => !count(links[key])) || typeof links.coverageComplete !== 'boolean' || !Array.isArray(links.results) || !Array.isArray(links.brokenLinks) || !Array.isArray(links.serverErrors) || !Array.isArray(links.unknownLinks)) return fail('invalid link check totals');
    if (links.results.some((entry) => !object(entry) || typeof entry.url !== 'string' || typeof entry.reason !== 'string' || !optionalText(entry.method) || !['ok', 'broken', 'server-error', 'unknown', 'unchecked'].includes(String(entry.status)) || (entry.statusCode !== null && !count(entry.statusCode)))) return fail('invalid link results');
    if (links.updatedAt !== undefined && (typeof links.updatedAt !== 'string' || !Number.isFinite(Date.parse(links.updatedAt)))) return fail('invalid link check date');
  }
  if (value.brandKit !== undefined) {
    if (!object(value.brandKit)) return fail('invalid brand observations');
    const typography = value.brandKit.typography;
    if (typography !== undefined && (!object(typography) || !strings(typography.primaryFamilies))) return fail('invalid font declarations');
  }
  if (value.drift !== undefined && value.drift !== null && (!object(value.drift) || typeof value.drift.hasChanges !== 'boolean')) return fail('invalid capture comparison');
  if (value.resources !== undefined) {
    if (!Array.isArray(value.resources)) return fail('invalid resource inventory');
    for (const entry of value.resources) {
      if (!object(entry) || typeof entry.id !== 'string' || typeof entry.url !== 'string' || typeof entry.type !== 'string' || !['image', 'audio', 'video', 'transcript', 'document', 'font', 'stylesheet', 'script', 'other'].includes(entry.type)) return fail('invalid resource inventory');
      if (['mimeType', 'checkStatus', 'downloadState', 'localPath', 'error', 'downloadReason', 'sha256', 'sourceSha256', 'localFileStatus', 'proposedLocalPath'].some((key) => !optionalText(entry[key]))) return fail('invalid resource text fields');
      if ((entry.statusCode !== undefined && entry.statusCode !== null && !count(entry.statusCode)) || (entry.bytes !== undefined && !count(entry.bytes)) || (entry.sourceBytes !== undefined && !count(entry.sourceBytes))) return fail('invalid resource metrics');
      if (!Array.isArray(entry.references) || entry.references.some((reference) => !object(reference) || typeof reference.pageUrl !== 'string' || typeof reference.role !== 'string' || !optionalText(reference.label) || !optionalText(reference.language))) return fail('invalid resource references');
    }
  }
  const intel = value.siteIntel;
  if (intel !== undefined) {
    if (!object(intel)) return fail('invalid site intelligence');
    const contacts = intel.contacts;
    if (contacts !== undefined && (!object(contacts) || !strings(contacts.emails) || !strings(contacts.phones) || !strings(contacts.socialProfiles))) return fail('invalid contacts');
    const tech = intel.techStack;
    if (tech !== undefined) {
      if (!object(tech) || !Array.isArray(tech.analyticsAndPixels) || tech.analyticsAndPixels.some((entry) => !object(entry) || typeof entry.name !== 'string' || typeof entry.category !== 'string') || !strings(tech.cmsOrFramework) || !strings(tech.hostingAndCdn)) return fail('invalid technology observations');
      if (!object(tech.measurementIds) || ['ga4', 'gtm', 'googleAds'].some((key) => !strings((tech.measurementIds as ObjectValue)[key]))) return fail('invalid measurement IDs');
      if (!object(tech.securityHeaders) || !strings(tech.securityHeaders.present) || !strings(tech.securityHeaders.missing)) return fail('invalid header observations');
      const consistency = (tech.securityHeaders as ObjectValue).consistency;
      if (consistency !== undefined && (!object(consistency) || !count(consistency.sampledPages) || !strings(consistency.inconsistent) || !strings(consistency.notes) || !Array.isArray(consistency.headers) || consistency.headers.some((row) => !object(row) || typeof row.header !== 'string' || !count(row.presentOn) || !count(row.of) || !['all', 'some', 'none'].includes(String(row.state)) || !strings(row.missingOn)))) return fail('invalid header consistency');
      const coverage = tech.coverage;
      if (coverage !== undefined && (!object(coverage) || !count(coverage.sampledPages) || !count(coverage.capturedHtmlPages) || !strings(coverage.sourceUrls) || typeof coverage.selection !== 'string' || typeof coverage.securityHeadersScope !== 'string')) return fail('invalid technology coverage');
    }
    const ai = intel.aiReadiness;
    if (ai !== undefined && (!object(ai) || !object(ai.endpoints) || ['llmsTxt', 'llmsFullTxt', 'aiCatalogJson', 'securityTxt', 'adsTxt'].some((key) => typeof (ai.endpoints as ObjectValue)[key] !== 'boolean') || !object(ai.aiBotsPolicy) || !Object.values(ai.aiBotsPolicy).every((entry) => typeof entry === 'string') || !strings(ai.blockedAiBots) || !strings(ai.savedFiles) || !count(ai.allowedAiBotsCount))) return fail('invalid discovery observations');
    const funnel = intel.funnel;
    if (funnel !== undefined && (!object(funnel) || ['formsCount', 'videosCount', 'downloadsCount'].some((key) => !count(funnel[key])) || !Array.isArray(funnel.platforms) || funnel.platforms.some((entry) => !object(entry) || typeof entry.platform !== 'string' || typeof entry.category !== 'string' || !strings(entry.urls)))) return fail('invalid funnel observations');
    const registration = intel.domainRegistration;
    if (registration !== undefined && (!object(registration) || ['registeredDate', 'expirationDate', 'updatedDate', 'registrar'].some((key) => registration[key] !== null && typeof registration[key] !== 'string') || (registration.domainAgeYears !== null && !count(registration.domainAgeYears)))) return fail('invalid domain registration');
  }
  return value as unknown as SiteGraphManifest;
}
