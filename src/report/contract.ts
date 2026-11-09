// The client report contract: an explicit allowlist of what may leave the agency in a client report file.
// Anything not named here is dropped when the map is built, and refused by the checker if it turns up in a file.
import type { SiteGraphManifest } from '../types/site';

/** Page fields the 3D map and its labels read. Notes, snapshots, file paths, raw text and per-page check detail are not listed. */
export const MAP_NODE_FIELDS = [
  'id', 'kind', 'health', 'flags', 'title', 'url', 'path', 'section', 'statusCode', 'inSitemap', 'urlDepth', 'clickDepth', 'wordCount',
  'inlinksBody', 'inlinksTotal', 'outlinksBody', 'outlinksTotal', 'externalDomainsOut', 'renderUsed',
] as const;
export const MAP_EDGE_FIELDS = ['id', 'source', 'target', 'kind'] as const;
export const MAP_SECTION_FIELDS = ['id', 'label', 'pageCount'] as const;
export const MAP_STAT_FIELDS = ['pagesCrawled', 'orphanPages', 'unlistedPages', 'brokenOrRedirectPages', 'externalDomains', 'externalEdges', 'internalEdges', 'sitemapUrlsTotal', 'sitemapsFound'] as const;
export const MAP_SITE_FIELDS = ['schemaVersion', 'siteId', 'domain', 'brandName', 'origin', 'capturedAt', 'captureStatus', 'stats', 'brandKit', 'sections', 'nodes', 'edges', 'audit'] as const;
/** Findings are kept only as far as the map needs to light up the pages that need attention. */
export const MAP_AUDIT_FINDING_FIELDS = ['id', 'category', 'tone', 'title', 'targets'] as const;

/** Top-level fields of a client report. */
export const REPORT_FIELDS = ['format', 'version', 'meta', 'client', 'feedback', 'labels', 'summary', 'findings', 'glossary', 'map', 'assets', 'modes', 'styles'] as const;

// Value checks (types, lengths, http(s) addresses, images, nested unknown keys). Same code as apps/server/ingest/contract-check.mjs.
export { reportValueProblems, isHttpUrl, REPORT_SPEC, REPORT_MAX_CHARS } from './contractValues';

type Rec = Record<string, unknown>;
const pick = (o: Rec, keys: readonly string[]): Rec => { const out: Rec = {}; for (const k of keys) if (o[k] !== undefined) out[k] = o[k]; return out; };

/** The map as the client file carries it: the allowlisted fields and nothing else. */
export function projectSite(m: SiteGraphManifest): Rec {
  const s = m as unknown as Rec;
  const audit = s.audit as { findings?: Rec[] } | undefined;
  return {
    ...pick(s, ['schemaVersion', 'siteId', 'domain', 'brandName', 'origin', 'capturedAt', 'captureStatus']),
    stats: pick((s.stats ?? {}) as Rec, MAP_STAT_FIELDS),
    // Local logo paths are vault references. The client map uses initials unless an embedded asset is supplied.
    brandKit: {},
    sections: ((s.sections ?? []) as Rec[]).map((x) => pick(x, MAP_SECTION_FIELDS)),
    nodes: (m.nodes as unknown as Rec[]).map((n) => pick(n, MAP_NODE_FIELDS)),
    edges: (m.edges as unknown as Rec[]).map((e) => pick(e, MAP_EDGE_FIELDS)),
    ...(audit?.findings ? { audit: { findings: audit.findings.map((f) => ({ ...pick(f, MAP_AUDIT_FINDING_FIELDS), targets: ((f.targets ?? []) as Rec[]).map((t) => pick(t, ['url'])) })) } } : {}),
  };
}

/** Names of fields in `site` that the contract does not allow. */
export function unlistedSiteFields(site: Rec): string[] {
  const bad: string[] = [];
  const check = (o: unknown, allowed: readonly string[], where: string) => {
    if (!o || typeof o !== 'object') return;
    for (const k of Object.keys(o)) if (!allowed.includes(k)) bad.push(`${where}.${k}`);
  };
  check(site, MAP_SITE_FIELDS, 'map.site');
  check(site.stats, MAP_STAT_FIELDS, 'map.site.stats');
  check(site.brandKit, ['localLogoAsset'], 'map.site.brandKit');
  for (const [name, list, fields] of [['sections', site.sections, MAP_SECTION_FIELDS], ['nodes', site.nodes, MAP_NODE_FIELDS], ['edges', site.edges, MAP_EDGE_FIELDS]] as const) {
    const seen = new Set<string>();
    for (const x of (Array.isArray(list) ? list : []) as Rec[]) for (const k of Object.keys(x)) if (!fields.some((field) => field === k) && !seen.has(k)) { seen.add(k); bad.push(`map.site.${name}[].${k}`); }
  }
  const findings = ((site.audit as { findings?: Rec[] } | undefined)?.findings ?? []);
  const seen = new Set<string>();
  for (const f of findings) for (const k of Object.keys(f)) if (!MAP_AUDIT_FINDING_FIELDS.some((field) => field === k) && !seen.has(k)) { seen.add(k); bad.push(`map.site.audit.findings[].${k}`); }
  return bad;
}
