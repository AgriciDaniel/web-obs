import { useMemo } from 'react';
import { XCircle } from 'lucide-react';
import type { SiteGraphManifest } from '../types/site';
import { captureDate } from '../data/sitePresentation';
import { mapSummary } from '../data/mapAttention';
import { formatCount } from './ui';

interface SiteOverviewProps {
  manifest: SiteGraphManifest;
  onPages: () => void;
  onAttention: () => void;
  onBrokenLinks: () => void;
  onDomains: () => void;
}

/** One compact line in the toolbar: who, when, and the four numbers worth a glance. */
export function SiteOverview({ manifest, onPages, onAttention, onBrokenLinks, onDomains }: SiteOverviewProps) {
  const summary = useMemo(() => mapSummary(manifest), [manifest]);
  const snapshot = manifest.captureStatus === 'partial' ? 'Partial' : manifest.preservationStatus === 'conflicts' ? 'Notes kept' : null;
  const snapshotTitle = manifest.captureStatus === 'partial' ? 'Partial snapshot' : 'Notes preserved';
  const mapped = manifest.nodes.filter((node) => node.kind === 'external-domain').length;
  const attentionTitle = summary.hasAudit
    ? `${formatCount(summary.attention)} items need attention. ${formatCount(summary.review)} more are worth reviewing in Site audit.`
    : 'Captured pages that failed to load. This capture has no audit findings.';
  return (
    <section className="wo-site-overview" aria-label="Capture summary">
      <div className="wo-site-identity" title={manifest.captureWarnings?.join('\n') || undefined}>
        <strong>{manifest.brandName || manifest.domain}</strong>
        <span>
          <time dateTime={manifest.capturedAt}>{captureDate(manifest.capturedAt)}</time>
          {snapshot && <span className="wo-snapshot-badge" title={snapshotTitle} aria-label={snapshotTitle}>{snapshot}</span>}
        </span>
      </div>
      <button type="button" className="wo-summary-stat" onClick={onPages} title={`${summary.pages} pages captured from ${manifest.stats.sitemapUrlsTotal} sitemap URLs. Open the page list.`}>
        <strong>{formatCount(summary.pages)}</strong><span>pages</span>
      </button>
      <button type="button" className={`wo-summary-stat ${summary.attention > 0 ? 'is-critical' : ''}`} onClick={onAttention} title={attentionTitle}>
        <strong>{summary.attention > 0 && <XCircle size={13} aria-hidden="true" />}{formatCount(summary.attention)}</strong><span>need attention</span>
      </button>
      <button type="button" className="wo-summary-stat" onClick={onBrokenLinks} title={`${summary.brokenDetail}. Open Site audit for link checks.`}>
        <strong>{formatCount(summary.brokenLinks)}</strong><span>broken links</span>
      </button>
      <button type="button" className="wo-summary-stat" onClick={onDomains} title={`${summary.externalDomains} external domains linked, ${mapped} shown in the saved map.`}>
        <strong>{formatCount(summary.externalDomains)}</strong><span>domains</span>
      </button>
    </section>
  );
}
