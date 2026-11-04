import type { SiteGraphManifest, SiteNode } from '../types/site';
import { buildSiteAudit } from './siteAudit';

/** Same page whether or not the URL ends in a slash or carries a fragment. */
const urlKey = (url: string) => url.replace(/#.*$/, '').replace(/\/+$/, '');

const isInternal = (node: SiteNode) => node.kind !== 'external-domain';
const isBrokenPage = (node: SiteNode) => isInternal(node) && (node.health === 'broken' || node.health === 'unavailable');

/**
 * Pages that need attention: targets of attention-tone audit findings plus pages that failed to load.
 * Review and coverage findings are deliberately left out, so a site where every page has a minor
 * note does not light up every row.
 */
export function attentionNodeIds(manifest: SiteGraphManifest | null): Set<string> {
  const ids = new Set<string>();
  if (!manifest) return ids;
  const byUrl = new Map<string, string>();
  for (const node of manifest.nodes) if (isInternal(node)) byUrl.set(urlKey(node.url), node.id);
  for (const finding of buildSiteAudit(manifest).findings) {
    if (finding.tone !== 'attention') continue;
    for (const target of finding.targets ?? []) {
      const id = target?.url ? byUrl.get(urlKey(target.url)) : undefined;
      if (id) ids.add(id);
    }
  }
  for (const node of manifest.nodes) if (isBrokenPage(node)) ids.add(node.id);
  return ids;
}

export interface MapSummary {
  pages: number;
  /** Items in attention-tone findings, counted exactly as the Site audit panel counts them. */
  attention: number;
  review: number;
  brokenLinks: number;
  brokenDetail: string;
  externalDomains: number;
  hasAudit: boolean;
}

const plural = (count: number, one: string, many: string) => `${count.toLocaleString('en-US')} ${count === 1 ? one : many}`;

export function mapSummary(manifest: SiteGraphManifest): MapSummary {
  // Same findings the Site audit panel shows, so the toolbar and the panel never disagree.
  const findings = buildSiteAudit(manifest).findings;
  const items = (tone: string) => findings.filter((f) => f.tone === tone)
    .reduce((sum, f) => sum + (f.totalTargets ?? f.targets.length), 0);
  const brokenPages = manifest.nodes.filter(isBrokenPage).length;
  const brokenTargets = Array.isArray(manifest.linkHealth?.brokenLinks) ? manifest.linkHealth!.brokenLinks.length : 0;
  const parts = [plural(brokenTargets, 'linked target returned 404 or 410', 'linked targets returned 404 or 410'), plural(brokenPages, 'captured page failed to load', 'captured pages failed to load')];
  return {
    pages: manifest.stats.pagesCrawled,
    attention: items('attention'),
    review: items('review'),
    brokenLinks: brokenTargets + brokenPages,
    brokenDetail: manifest.linkHealth ? parts.join('. ') : `${parts[1]}. Link checks were not recorded.`,
    externalDomains: manifest.stats.externalDomains,
    hasAudit: Boolean(manifest.audit),
  };
}

/** Highest authority first; captures without a score fall back to captured body inlinks. */
export function topAuthorityIds(nodes: readonly SiteNode[], limit = 10): Set<string> {
  const score = (node: SiteNode) => typeof node.authorityScore === 'number' ? node.authorityScore : node.inlinksBody;
  return new Set(nodes.filter((node) => node.kind === 'page')
    .sort((a, b) => score(b) - score(a) || a.path.localeCompare(b.path))
    .slice(0, limit).map((node) => node.id));
}

/**
 * Labels drawn at rest: home, section hubs, attention pages and the strongest pages. Small or
 * filtered maps label every visible node. Hover, selection and search add labels at runtime.
 */
export function restingLabelIds(visible: readonly SiteNode[], attention: ReadonlySet<string>, limit = 10, everyoneBelow = 20): Set<string> {
  if (visible.length <= everyoneBelow) return new Set(visible.map((node) => node.id));
  const ids = topAuthorityIds(visible, limit);
  for (const node of visible) {
    if (node.kind === 'home' || node.kind === 'hub' || attention.has(node.id)) ids.add(node.id);
  }
  return ids;
}
