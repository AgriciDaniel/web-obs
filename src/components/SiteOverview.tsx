import { ArrowUpRight, Clock3, Layers, ScanSearch } from 'lucide-react';
import type { SiteGraphManifest } from '../types/site';
import { captureDate } from '../data/sitePresentation';

interface SiteOverviewProps {
  manifest: SiteGraphManifest;
  onPages: () => void;
  onIssues: () => void;
  onDomains: () => void;
}

export function SiteOverview({ manifest, onPages, onIssues, onDomains }: SiteOverviewProps) {
  const mapped = manifest.nodes.filter((node) => node.kind === 'external-domain').length;
  const stats = manifest.stats;
  return (
    <section className="wo-site-overview" aria-label="Capture summary">
      <div className="wo-site-identity">
        <span className="wo-eyebrow">WEBSITE INTELLIGENCE <span className="wo-snapshot-badge" title={manifest.captureWarnings?.join("\n")}>{manifest.captureStatus === 'partial' ? 'Partial snapshot' : manifest.preservationStatus === 'conflicts' ? 'Notes preserved' : 'Saved snapshot'}</span></span>
        <h1>{manifest.brandName || manifest.domain}</h1>
        <span className="wo-capture-date"><Clock3 size={12} /><time dateTime={manifest.capturedAt}>Captured {captureDate(manifest.capturedAt)}</time></span>
      </div>
      <button type="button" className="wo-summary-stat" onClick={onPages}><span><Layers size={14} />Pages captured</span><strong>{stats.pagesCrawled}</strong><small>{stats.sitemapUrlsTotal} sitemap URLs found</small></button>
      <button type="button" className="wo-summary-stat" onClick={onIssues}><span><ScanSearch size={14} />Pages with audit flags</span><strong>{stats.pagesWithSeoIssues ?? 'No data'}</strong><small>{stats.pagesWithSeoIssues === undefined ? 'Not recorded in this capture' : 'Recorded checks, not a health score'}</small></button>
      <button type="button" className="wo-summary-stat" onClick={onDomains}><span><ArrowUpRight size={14} />External domains</span><strong>{stats.externalDomains}</strong><small className={mapped < stats.externalDomains ? 'wo-coverage-warning' : ''}>{mapped} represented in saved map</small></button>
    </section>
  );
}
