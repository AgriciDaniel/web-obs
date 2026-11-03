import { useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { ArrowUpRight, BarChart3, ChevronDown, FileText, Image as ImageIcon, Layers, Link2, Search, Shield, X } from 'lucide-react';
import type { SiteGraphManifest } from '../types/site';
import { captureDate } from '../data/sitePresentation';
import { AUDIT_CATEGORIES, buildSiteAudit, filterAuditFindings } from '../data/siteAudit';
import type { AuditBucket, AuditCategory, AuditFinding } from '../data/siteAudit';
import '../styles/audit.css';

export interface SiteAuditPanelProps {
  manifest: SiteGraphManifest;
  onClose: () => void;
  onInspectPage: (id: string) => void;
  onOpenNote: (path: string) => void;
  onContinueLinks?: () => void;
  onOpenExternalUrl: (url: string) => void;
}

const bucketColor = (bucket: AuditBucket) => {
  if (bucket.id === 'unchecked' || bucket.id === 'reference') return 'var(--ink-muted)';
  if (bucket.id === 'intentional' || bucket.id === 'unrecorded') return 'var(--border-strong)';
  return ({ good: 'var(--hub)', attention: 'var(--broken)', review: 'var(--orphan)', coverage: 'var(--ext)', neutral: 'var(--accent-bright)' })[bucket.tone];
};
const colorStyle = (bucket: AuditBucket): CSSProperties => ({ '--audit-color': bucketColor(bucket) } as CSSProperties);
const displayCount = (count: number) => count.toLocaleString();

function Distribution({ title, buckets, total }: { title: string; buckets: AuditBucket[]; total: number }) {
  let offset = 0;
  return <div className="wo-audit-distribution">
    <svg className="wo-audit-ring" viewBox="0 0 132 132" role="img" aria-label={`${title}: ${total ? buckets.filter(bucket => bucket.count > 0).map(bucket => `${bucket.label} ${bucket.count}`).join(', ') : 'no data'}`}>
      <circle className="wo-audit-ring-track" cx="66" cy="66" r="51" />
      {total > 0 && buckets.filter(bucket => bucket.count > 0).map(bucket => {
        const length = bucket.count / total * 320.44;
        const previous = offset;
        offset += length;
        return <circle key={bucket.id} className="wo-audit-ring-segment" cx="66" cy="66" r="51" stroke={bucketColor(bucket)} strokeDasharray={`${Math.max(0, length - 2)} ${320.44 - Math.max(0, length - 2)}`} strokeDashoffset={-previous} />;
      })}
      <text className="wo-audit-ring-number" x="66" y="65" textAnchor="middle">{total ? displayCount(total) : 'No data'}</text>
      {total > 0 && <text className="wo-audit-ring-caption" x="66" y="83" textAnchor="middle">observed</text>}
    </svg>
    <ul className="wo-audit-legend">
      {buckets.map(bucket => <li key={bucket.id} style={colorStyle(bucket)}><span className="wo-audit-swatch" aria-hidden="true" /><span>{bucket.label}</span><strong>{displayCount(bucket.count)}</strong></li>)}
    </ul>
  </div>;
}

function FindingGroup({ group, onInspectPage, onOpenNote, onOpenExternalUrl }: Pick<SiteAuditPanelProps, 'onInspectPage' | 'onOpenNote' | 'onOpenExternalUrl'> & { group: AuditFinding }) {
  const [limit, setLimit] = useState(12);
  const severity = { attention: 'Recorded error', review: 'Review context', coverage: 'Coverage gap' }[group.tone];
  const category = AUDIT_CATEGORIES.find(item => item.id === group.category)?.label;
  return <details className={`wo-audit-finding wo-audit-finding-${group.tone}`}>
    <summary className="wo-audit-finding-summary">
      <span className="wo-audit-finding-marker" aria-hidden="true" />
      <span className="wo-audit-finding-heading"><strong>{group.title}</strong><span>{category} · {severity}</span></span>
      <span className="wo-audit-finding-count">{displayCount(group.targets.length)} <span>affected</span></span>
      <ChevronDown size={16} className="wo-audit-chevron" aria-hidden="true" />
    </summary>
    <div className="wo-audit-finding-content">
      <p>{group.explanation}</p>
      <ul className="wo-audit-targets">
        {group.targets.slice(0, limit).map(target => <li key={target.id}>
          <div className="wo-audit-target-text"><strong>{target.label}</strong><span>{target.url}</span>{target.detail && <small>{target.detail}</small>}</div>
          <div className="wo-audit-target-actions">
            {target.pageId && <button type="button" className="wo-audit-text-button" onClick={() => onInspectPage(target.pageId!)}>Inspect page</button>}
            {!target.pageId && target.sourcePageId && <button type="button" className="wo-audit-text-button" onClick={() => onInspectPage(target.sourcePageId!)}>Inspect source</button>}
            {target.notePath && <button type="button" className="wo-audit-text-button" onClick={() => onOpenNote(target.notePath!)}>Open note</button>}
            <button type="button" className="wo-audit-text-button" onClick={() => onOpenExternalUrl(target.url)}>Open URL <ArrowUpRight size={12} aria-hidden="true" /></button>
          </div>
        </li>)}
      </ul>
      {group.targets.length > limit && <button type="button" className="wo-audit-button wo-audit-button-subtle" onClick={() => setLimit(current => current + 24)}>Show {Math.min(24, group.targets.length - limit)} more of {displayCount(group.targets.length)} affected items</button>}
    </div>
  </details>;
}

export function SiteAuditPanel({ manifest, onClose, onInspectPage, onOpenNote, onContinueLinks, onOpenExternalUrl }: SiteAuditPanelProps) {
  const audit = useMemo(() => buildSiteAudit(manifest), [manifest]);
  const [category, setCategory] = useState<AuditCategory | 'all'>('all');
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => filterAuditFindings(audit.findings, category, query), [audit, category, query]);
  const groupCount = (value: AuditCategory) => audit.findings.filter(group => group.category === value).length;
  const maxSection = Math.max(1, ...audit.pageSections.map(section => section.count));
  const shownTargets = filtered.reduce((sum, group) => sum + group.targets.length, 0);
  const hasObservations = audit.pageCount > 0 || audit.linkTotal > 0 || audit.resourceCount > 0;
  return <section className="wo-audit-panel" aria-label={`Site audit for ${manifest.domain}`}>
    <header className="wo-audit-header">
      <div className="wo-audit-heading"><span className="wo-audit-kicker"><BarChart3 size={13} aria-hidden="true" /> Saved website evidence</span><h1>Site audit <span>{manifest.domain}</span></h1><p>Captured {captureDate(manifest.capturedAt)} · Findings from the saved capture</p></div>
      <div className="wo-audit-header-actions"><button type="button" className="wo-audit-button" onClick={() => onOpenNote(`sites/${manifest.siteId}/_link-health.md`)}><FileText size={14} aria-hidden="true" /> Link report</button><button type="button" className="wo-audit-close" onClick={onClose} aria-label="Close audit" title="Close audit"><X size={20} aria-hidden="true" /></button></div>
    </header>
    <div className="wo-audit-body">
      <div className="wo-audit-intro">
        <div><h2>Your capture, made actionable.</h2><p>Review recorded findings and follow each one to its source. Unchecked and inconclusive observations remain visible.</p></div>
        <span className={`wo-audit-capture-state ${manifest.captureStatus === 'partial' ? 'wo-audit-state-partial' : ''}`}>{manifest.captureStatus === 'partial' ? 'Partial collection' : manifest.captureStatus === 'complete' ? 'Capture saved' : 'Legacy capture'}</span>
      </div>
      <div className="wo-audit-stats">
        <div className="wo-audit-stat"><Layers size={17} aria-hidden="true" /><div><strong>{audit.pageCount ? displayCount(audit.pageCount) : 'No data'}</strong><span>Captured pages</span></div></div>
        <div className="wo-audit-stat"><BarChart3 size={17} aria-hidden="true" /><div><strong>{hasObservations ? displayCount(audit.findingCount) : 'No data'}</strong><span>Recorded findings <small>across {audit.findings.length} groups</small></span></div></div>
        <div className="wo-audit-stat"><Link2 size={17} aria-hidden="true" /><div><strong>{audit.linkTotal && audit.linkAttempted !== null ? `${displayCount(audit.linkAttempted)} / ${displayCount(audit.linkTotal)}` : 'No data'}</strong><span>Link targets attempted</span></div></div>
        <div className="wo-audit-stat"><ImageIcon size={17} aria-hidden="true" /><div><strong>{audit.resourceCount ? displayCount(audit.resourceCount) : 'No data'}</strong><span>Observed media and resources</span></div></div>
      </div>
      <div className="wo-audit-charts">
        <article className="wo-audit-card"><div className="wo-audit-card-head"><Link2 size={15} aria-hidden="true" /><h3>Destination checks</h3><span>Saved responses</span></div><Distribution title="Link status distribution" buckets={audit.linkDistribution} total={audit.linkTotal} /><button type="button" className="wo-audit-text-button" onClick={() => onOpenNote(`sites/${manifest.siteId}/_link-health.md`)}>Open link report <ArrowUpRight size={12} aria-hidden="true" /></button><p className="wo-audit-note">{audit.linkTotal ? 'A response is evidence for check time only. Inconclusive and unchecked targets are not counted as working links.' : 'No data. No destination check observations were saved.'}</p>{audit.linkPending > 0 && onContinueLinks && <button type="button" className="wo-audit-text-button" onClick={onContinueLinks}>Check remaining {displayCount(audit.linkPending)} targets <ArrowUpRight size={13} aria-hidden="true" /></button>}</article>
        <article className="wo-audit-card"><div className="wo-audit-card-head"><Layers size={15} aria-hidden="true" /><h3>Pages by section</h3><span>{audit.pageCount} mapped</span></div><div className="wo-audit-section-bars" aria-label="Captured pages by section">{audit.pageSections.length ? audit.pageSections.slice(0, 7).map(section => <div className="wo-audit-bar-row" key={section.id}><div><span>{section.label}</span><strong>{displayCount(section.count)}</strong></div><div className="wo-audit-bar-track"><span style={{ width: `${section.count / maxSection * 100}%` }} /></div></div>) : <p className="wo-audit-empty-chart">No data</p>}</div>{audit.pageSections.length > 7 && <details className="wo-audit-more-sections"><summary>All {audit.pageSections.length} sections</summary><ul>{audit.pageSections.map(section => <li key={section.id}><span>{section.label}</span><strong>{displayCount(section.count)}</strong></li>)}</ul></details>}<p className="wo-audit-note">Counts come from captured internal pages. External domains and undiscovered pages are excluded.</p></article>
        <article className="wo-audit-card"><div className="wo-audit-card-head"><ImageIcon size={15} aria-hidden="true" /><h3>Media inventory</h3><span>Local preservation</span></div><Distribution title="Resource download states" buckets={audit.mediaDistribution} total={audit.resourceCount} /><p className="wo-audit-note">Intentionally unselected variants and reference-only resources are separate from download failures.</p>{audit.mediaTypes.length > 0 ? <details className="wo-audit-media-types"><summary>Resource types <ChevronDown size={12} aria-hidden="true" /></summary><ul className="wo-audit-legend">{audit.mediaTypes.map(type => <li key={type.id}><span>{type.label}</span><strong>{displayCount(type.count)}</strong></li>)}</ul></details> : <p className="wo-audit-note">No data. No resource observations were saved.</p>}</article>
      </div>
      <div className="wo-audit-lower-grid">
        <section className="wo-audit-inbox" aria-label="Recorded findings inbox">
          <div className="wo-audit-inbox-head"><div><span className="wo-audit-kicker">From observation to action</span><h2>Recorded findings</h2></div><span className="wo-audit-total">{audit.findings.length} groups</span></div>
          <label className="wo-audit-search"><Search size={16} aria-hidden="true" /><span className="wo-audit-sr-only">Search recorded findings and affected URLs</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search findings, pages, or URLs" /></label>
          <div className="wo-audit-categories" role="group" aria-label="Filter findings by category"><button type="button" aria-pressed={category === 'all'} onClick={() => setCategory('all')}>All <span>{audit.findings.length}</span></button>{AUDIT_CATEGORIES.map(item => <button key={item.id} type="button" aria-pressed={category === item.id} onClick={() => setCategory(item.id)}>{item.label} <span>{groupCount(item.id)}</span></button>)}</div>
          <p className="wo-audit-filter-count" role="status">{filtered.length} groups · {displayCount(shownTargets)} affected items{query && ` matching “${query}”`}</p>
          <div className="wo-audit-findings">{filtered.length ? filtered.map(group => <FindingGroup key={`${manifest.siteId}:${group.id}:${query}`} group={group} onInspectPage={onInspectPage} onOpenNote={onOpenNote} onOpenExternalUrl={onOpenExternalUrl} />) : <div className="wo-audit-empty"><Search size={24} aria-hidden="true" /><h3>{audit.findings.length ? 'No matching findings' : hasObservations ? 'No findings recorded' : 'No data'}</h3><p>{audit.findings.length ? 'Try another category or search term.' : 'This capture contains no recorded findings for these signals. Unassessed areas remain listed separately.'}</p>{(query || category !== 'all') && <button type="button" className="wo-audit-text-button" onClick={() => { setQuery(''); setCategory('all'); }}>Clear filters</button>}</div>}</div>
        </section>
        <aside className="wo-audit-evidence" aria-label="Audit scope and evidence">
          <article className="wo-audit-card"><div className="wo-audit-card-head"><Shield size={15} aria-hidden="true" /><h3>Homepage headers</h3></div>{audit.headers && (audit.headers.present.length || audit.headers.missing.length) ? <><div className="wo-audit-header-tally"><strong>{audit.headers.present.length}</strong><span>present <small>of {audit.headers.present.length + audit.headers.missing.length} recorded checks</small></span></div><p className="wo-audit-note">{audit.headers.scope}</p><ul className="wo-audit-header-list">{audit.headers.present.map(header => <li key={header}><span>{header}</span><span>Present</span></li>)}{audit.headers.missing.map(header => <li key={header}><span>{header}</span><span className="wo-audit-review-text">Not observed</span></li>)}</ul></> : <p className="wo-audit-note">No data. Header presence was not recorded.</p>}<p className="wo-audit-note">Presence checks on one response do not establish site-wide security or legal compliance.</p></article>
          <article className="wo-audit-card"><div className="wo-audit-card-head"><ImageIcon size={15} aria-hidden="true" /><h3>Image text observations</h3></div><div className="wo-audit-header-tally"><strong>{audit.imageMetricPages ? displayCount(audit.imagesMissingAlt) : 'No data'}</strong><span>without alt text <small>{audit.imageMetricPages ? `from ${audit.imageMetricPages} pages with recorded metrics` : 'metric was not recorded'}</small></span></div><p className="wo-audit-note">Image purpose and decorative use need review. Alt text observations do not establish accessibility conformance.</p></article>
          <article className="wo-audit-card wo-audit-scope"><span className="wo-audit-kicker">Know the scope</span><h3>Not assessed</h3><ul>{audit.notAssessed.map(area => <li key={area}><span>{area}</span><span>Not assessed</span></li>)}</ul><p className="wo-audit-note">These require separate evidence and review. There is no overall health grade.</p></article>
        </aside>
      </div>
      {(manifest.captureWarnings?.length ?? 0) > 0 && <details className="wo-audit-warnings"><summary>{manifest.captureWarnings!.length} capture warnings</summary><ul>{manifest.captureWarnings!.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
      <footer className="wo-audit-footer"><span>Saved observations · No new scan is running</span><button type="button" className="wo-audit-text-button" onClick={() => onOpenNote(`sites/${manifest.siteId}/_dashboard.md`)}>Open capture dashboard <ArrowUpRight size={12} aria-hidden="true" /></button></footer>
    </div>
  </section>;
}
