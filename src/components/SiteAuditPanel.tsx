import { useMemo, useState } from 'react';
import { AlertTriangle, ArrowUpRight, CheckSquare, ChevronDown, FileSpreadsheet, FileText, Link2, Search, X, XCircle } from 'lucide-react';
import type { AuditActions, SiteGraphManifest } from '../types/site';
import { useAuditActions } from './AuditActionsBar';
import { captureDate } from '../data/sitePresentation';
import { AUDIT_CATEGORIES, buildSiteAudit, filterAuditFindings } from '../data/siteAudit';
import type { AuditBucket, AuditCategory, AuditFinding } from '../data/siteAudit';
import { Disclosure, KeyValueList, RankedBars, SegmentedBar, StatRow, StatTile, StatusPill, formatCount } from './ui';
import type { Part, Status } from './ui';
import '../styles/audit.css';

export interface SiteAuditPanelProps {
  manifest: SiteGraphManifest;
  onClose: () => void;
  onInspectPage: (id: string) => void;
  onOpenNote: (path: string) => void;
  onContinueLinks?: () => void;
  onOpenExternalUrl: (url: string) => void;
  /** Optional: Publish audit and Archive audit (Obsidian desktop only). */
  actions?: AuditActions;
  /** After a capture was archived, so the view can refresh its list of sites. */
  onArchived?: () => void;
}

type FindingTone = AuditFinding['tone'];
const TONES: Array<{ id: FindingTone; title: string }> = [
  { id: 'attention', title: 'Needs attention' },
  { id: 'review', title: 'Worth reviewing' },
  { id: 'coverage', title: 'Coverage gaps' },
];
/** Rows shown per severity group before a "show more" button. */
const GROUP_ROW_LIMIT = 8;
const categoryLabel = (id: AuditCategory) => AUDIT_CATEGORIES.find(item => item.id === id)?.label ?? id;
const size = (group: AuditFinding) => group.totalTargets ?? group.targets.length;
const plural = (count: number, word: string) => `${formatCount(count)} ${word}${count === 1 ? '' : 's'}`;

/** Status colours only where the bucket is a status; "not looked at" buckets stay grey. */
const bucketStatus: Record<AuditBucket['tone'], Status> = { good: 'good', attention: 'critical', review: 'warning', coverage: 'info', neutral: 'neutral' };
const toParts = (buckets: AuditBucket[]): Part[] => buckets.map(bucket => ({
  id: bucket.id, label: bucket.label, value: bucket.count, status: bucketStatus[bucket.tone],
  color: bucket.id === 'unchecked' || bucket.id === 'reference' ? 'var(--ink-muted)' : undefined,
}));

function FindingRow({ group, siteId, onInspectPage, onOpenNote, onOpenExternalUrl }: Pick<SiteAuditPanelProps, 'onInspectPage' | 'onOpenNote' | 'onOpenExternalUrl'> & { group: AuditFinding; siteId: string }) {
  const [limit, setLimit] = useState(8);
  return <details className={`wo-audit-finding is-${group.tone}`}>
    <summary className="wo-audit-finding-summary">
      {group.tone === 'attention' ? <XCircle size={14} className="wo-audit-finding-icon" aria-hidden="true" /> : <span className="wo-audit-finding-icon" aria-hidden="true" />}
      <span className="wo-audit-finding-title">{group.title}</span>
      <span className="wo-audit-chip">{categoryLabel(group.category)}</span>
      <span className="wo-audit-finding-count" title={`${plural(size(group), 'affected item')}`}>{formatCount(size(group))}</span>
      <ChevronDown size={14} className="wo-audit-chevron" aria-hidden="true" />
    </summary>
    <div className="wo-audit-finding-content">
      <p>{group.explanation}</p>
      <ul className="wo-audit-targets">
        {group.targets.slice(0, limit).map(target => <li key={target.id}>
          <div className="wo-audit-target-text">
            <span className="wo-audit-target-label">{target.label}</span>
            {target.url !== target.label && <span className="wo-audit-target-url">{target.url}</span>}
            {target.detail && <span className="wo-audit-target-detail">{target.detail}</span>}
          </div>
          <div className="wo-audit-target-actions">
            {target.pageId && <button type="button" className="wo-audit-link" onClick={() => onInspectPage(target.pageId!)}>Inspect page</button>}
            {!target.pageId && target.sourcePageId && <button type="button" className="wo-audit-link" onClick={() => onInspectPage(target.sourcePageId!)}>Inspect source</button>}
            {target.notePath && <button type="button" className="wo-audit-icon-button" onClick={() => onOpenNote(target.notePath!)} aria-label="Open note" title="Open note"><FileText size={13} aria-hidden="true" /></button>}
            <button type="button" className="wo-audit-icon-button" onClick={() => onOpenExternalUrl(target.url)} aria-label="Open URL" title="Open URL"><ArrowUpRight size={13} aria-hidden="true" /></button>
          </div>
        </li>)}
      </ul>
      {group.targets.length > limit && <button type="button" className="wo-audit-link" onClick={() => setLimit(current => current + 24)}>Show {Math.min(24, group.targets.length - limit)} more of {formatCount(group.targets.length)}</button>}
      {group.totalTargets !== undefined && group.totalTargets > group.targets.length && <p className="wo-audit-note">The capture stored the first {formatCount(group.targets.length)} of {formatCount(group.totalTargets)} items. Every row is in <button type="button" className="wo-audit-link" onClick={() => onOpenNote(`sites/${siteId}/_findings.csv`)}>_findings.csv</button>.</p>}
    </div>
  </details>;
}

function ContentAndBrowser({ manifest }: { manifest: SiteGraphManifest }) {
  const audit = manifest.audit;
  const browser = manifest.siteIntel?.browserAudit;
  const dup = audit?.duplicates;
  const fresh = audit?.freshness;
  const trust = audit?.trust;
  const phrases = audit?.keywords?.bigrams?.slice(0, 8) ?? [];
  const pages = (browser?.pages ?? []).filter(page => !page.error);
  const lcp = pages.map(page => page.lab?.lcpMs).filter((value): value is number => typeof value === 'number');
  const jsPages = pages.filter(page => (page.jsGap?.wordsAddedByJsPct ?? 0) >= 20).length;
  const hosts = new Map<string, number>();
  pages.forEach(page => page.thirdParty?.hosts.forEach(host => hosts.set(host.host, (hosts.get(host.host) ?? 0) + host.requests)));
  const rules = new Map<string, number>();
  pages.forEach(page => page.a11y?.violations?.forEach(rule => rules.set(rule.help, (rules.get(rule.help) ?? 0) + 1)));
  const found = (value: string | null | undefined): { value: string; status: Status } => value ? { value: 'Found', status: 'good' as const } : { value: 'Not found', status: 'warning' as const };
  return <>
    {audit && (dup || fresh || trust) && <Disclosure summary="Content summary">
      <KeyValueList rows={[
        ...(dup ? [{ label: 'Duplicate titles / descriptions', value: `${dup.titles.length} / ${dup.descriptions.length}` },
          { label: 'Identical / near identical content', value: `${dup.exactContent.length} / ${dup.nearContent.length}` }] : []),
        { label: 'Pages competing for one topic', value: formatCount(audit.cannibalization?.length ?? 0) },
        ...(fresh ? [{ label: 'Dated / undated / stale pages', value: `${fresh.datedCount} / ${fresh.undatedCount} / ${fresh.stale.length}` },
          { label: 'Newest date', value: fresh.newest?.date ?? 'No data' }] : []),
        ...(trust ? [
          { label: 'About page', ...found(trust.about) }, { label: 'Contact page', ...found(trust.contact) },
          { label: 'Privacy page', ...found(trust.privacy) }, { label: 'Terms page', ...found(trust.terms) },
          { label: 'Pages with an author byline', value: `${trust.pagesWithAuthor} of ${trust.pagesChecked}` }] : []),
      ]} />
      {phrases.length > 0 && <><h4>Top phrases across the site</h4>
        <RankedBars label="Top phrases across the site" bars={phrases.map(row => ({ id: row.term, label: row.term, value: row.count, hint: row.pages ? `on ${row.pages} pages` : undefined }))} /></>}
    </Disclosure>}
    {browser && <Disclosure summary="Browser sample" count={pages.length}>
      {pages.length ? <>
        <KeyValueList rows={[
          { label: 'Pages sampled', value: `${pages.length} of ${browser.sampledUrls?.length ?? pages.length}` },
          { label: 'Largest paint (lab)', value: lcp.length ? `${Math.min(...lcp)} to ${Math.max(...lcp)} ms` : 'No data' },
          { label: 'Pages relying on JavaScript', value: formatCount(jsPages), title: 'At least 20% of words added by JavaScript' },
          { label: 'Third-party hosts on first load', value: formatCount(hosts.size) },
          { label: 'Automated accessibility rules failed', value: formatCount(rules.size) },
        ]} />
        {rules.size > 0 && <><h4>Accessibility rules failed</h4>
          <RankedBars label="Accessibility rules failed, by pages" bars={[...rules].map(([help, count]) => ({ id: help, label: help, value: count, hint: 'pages' }))} /></>}
        {hosts.size > 0 && <><h4>Third-party requests</h4>
          <RankedBars label="Third-party requests by host" bars={[...hosts].map(([host, count]) => ({ id: host, label: host, value: count, hint: 'requests' }))} /></>}
      </> : <p className="wo-audit-note">{browser.detail ?? 'No pages were sampled in a browser.'}</p>}
    </Disclosure>}
  </>;
}

export function SiteAuditPanel({ manifest, onClose, onInspectPage, onOpenNote, onContinueLinks, onOpenExternalUrl, actions, onArchived }: SiteAuditPanelProps) {
  const audit = useMemo(() => buildSiteAudit(manifest), [manifest]);
  const [category, setCategory] = useState<AuditCategory | 'all'>('all');
  const [query, setQuery] = useState('');
  const [expandedTones, setExpandedTones] = useState<Set<FindingTone>>(() => new Set());
  const filtered = useMemo(() => filterAuditFindings(audit.findings, category, query), [audit, category, query]);
  const notePath = (name: string) => `sites/${manifest.siteId}/${name}`;
  const extras = audit.extras;

  const toneTotals = useMemo(() => {
    const totals = { attention: { groups: 0, items: 0 }, review: { groups: 0, items: 0 }, coverage: { groups: 0, items: 0 } };
    for (const group of audit.findings) { totals[group.tone].groups += 1; totals[group.tone].items += size(group); }
    return totals;
  }, [audit]);
  const categoryCounts = useMemo(() => {
    const counts = new Map<AuditCategory, { groups: number; items: number }>();
    for (const group of audit.findings) {
      const entry = counts.get(group.category) ?? { groups: 0, items: 0 };
      entry.groups += 1; entry.items += size(group);
      counts.set(group.category, entry);
    }
    return counts;
  }, [audit]);
  const visibleCategories = AUDIT_CATEGORIES.filter(item => categoryCounts.has(item.id) || item.id === category);
  const shownTargets = filtered.reduce((sum, group) => sum + group.targets.length, 0);
  const hasObservations = audit.pageCount > 0 || audit.linkTotal > 0 || audit.resourceCount > 0;
  const broken = audit.linkDistribution.find(bucket => bucket.id === 'broken')?.count ?? 0;

  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  const filterBy = (value: AuditCategory) => { setCategory(value); setQuery(''); window.requestAnimationFrame(() => scrollTo('wo-audit-findings')); };
  const captureStatus: { status: Status; label: string } = manifest.captureStatus === 'partial'
    ? { status: 'warning', label: 'Partial collection' }
    : manifest.captureStatus === 'complete' ? { status: 'good', label: 'Capture saved' } : { status: 'neutral', label: 'Legacy capture' };

  const workItems = extras ? [
    { label: 'Internal link opportunities', value: extras.linkOpportunities, hint: 'Heuristic suggestions to review' },
    { label: 'Internal links to fix', value: extras.linkFixes, hint: 'Internal links that point at a recorded problem' },
    { label: 'Duplicate groups', value: extras.duplicateGroups, hint: 'Titles, descriptions and content' },
    ...(audit.imageMetricPages ? [{ label: 'Images without alt text', value: audit.imagesMissingAlt, hint: `From ${audit.imageMetricPages} pages with recorded metrics` }] : []),
  ] : [];

  const auditUi = useAuditActions({ manifest, actions, onOpenUrl: onOpenExternalUrl, onArchived: onArchived ?? (() => {}) });

  return <section className="wo-audit-panel" aria-label={`Site audit for ${manifest.domain}`}>
    <header className="wo-audit-header">
      <div className="wo-audit-heading">
        <h1>Site audit <span>{manifest.domain}</span></h1>
        <p><StatusPill status={captureStatus.status} label={captureStatus.label} /><span>Captured {captureDate(manifest.capturedAt)}. Saved observations, no new scan is running.</span></p>
      </div>
      <div className="wo-audit-actions" role="group" aria-label="Audit notes">
        <button type="button" className="wo-audit-button" onClick={() => onOpenNote(notePath('_audit.md'))}><FileText size={14} aria-hidden="true" /> Audit report</button>
        {extras?.tasks && <button type="button" className="wo-audit-button" onClick={() => onOpenNote(notePath('_tasks.md'))}><CheckSquare size={14} aria-hidden="true" /> Task list</button>}
        <button type="button" className="wo-audit-button" onClick={() => onOpenNote(notePath('_findings.csv'))}><FileSpreadsheet size={14} aria-hidden="true" /> Findings CSV</button>
        <button type="button" className="wo-audit-button" onClick={() => onOpenNote(notePath('_link-health.md'))}><Link2 size={14} aria-hidden="true" /> Link report</button>
        {auditUi.buttons}
      </div>
      <button type="button" className="wo-audit-close" onClick={onClose} aria-label="Close audit" title="Close audit"><X size={18} aria-hidden="true" /></button>
    </header>
    {auditUi.dialogs}

    <div className="wo-audit-body">
      <div className="wo-audit-content">
        <div className="wo-audit-stats">
          <StatRow label="Audit summary">
            <StatTile label="Needs attention" icon={<XCircle size={13} className="wo-audit-icon-critical" aria-hidden="true" />}
              value={hasObservations ? formatCount(toneTotals.attention.items) : 'No data'}
              hint={plural(toneTotals.attention.groups, 'finding')}
              onClick={toneTotals.attention.groups ? () => scrollTo('wo-audit-group-attention') : undefined} />
            <StatTile label="To review" icon={<AlertTriangle size={13} className="wo-audit-icon-warning" aria-hidden="true" />}
              value={hasObservations ? formatCount(toneTotals.review.items) : 'No data'}
              hint={plural(toneTotals.review.groups, 'finding')}
              onClick={toneTotals.review.groups ? () => scrollTo('wo-audit-group-review') : undefined} />
            <StatTile label="Pages" value={audit.pageCount ? formatCount(audit.pageCount) : 'No data'} hint={plural(audit.pageSections.length, 'section')} />
            <StatTile label="Links checked"
              value={audit.linkTotal && audit.linkAttempted !== null ? `${formatCount(audit.linkAttempted)} of ${formatCount(audit.linkTotal)}` : 'No data'}
              hint={audit.linkTotal ? `${formatCount(broken)} broken` : 'Not recorded'} />
            <StatTile label="Open tasks" icon={<CheckSquare size={13} aria-hidden="true" />} value={extras?.tasks ? formatCount(extras.tasks.open) : 'No data'}
              hint={extras?.tasks ? `${formatCount(extras.tasks.resolved)} resolved` : 'Task list not recorded'}
              onClick={extras?.tasks ? () => onOpenNote(notePath('_tasks.md')) : undefined} />
          </StatRow>
        </div>

        {workItems.length > 0 && <div className="wo-audit-work" role="list" aria-label="Audit work lists">
          <span className="wo-audit-work-title">Work list</span>
          {workItems.map(item => <span key={item.label} className="wo-audit-work-item" role="listitem" title={item.hint}>
            {item.label}<b>{formatCount(item.value)}</b>
          </span>)}
        </div>}

        <div className="wo-audit-charts">
          <article className="wo-audit-card">
            <header className="wo-audit-card-head"><h3>Findings by category</h3><span>Affected items</span></header>
            {categoryCounts.size ? <RankedBars label="Affected items by finding category"
              bars={[...categoryCounts].map(([id, entry]) => ({ id, label: categoryLabel(id), value: entry.items, hint: `${plural(entry.groups, 'finding')}. Select to filter the list`, onClick: () => filterBy(id) }))} />
              : <p className="wo-audit-empty-chart">{hasObservations ? 'No findings recorded' : 'No data'}</p>}
          </article>
          <article className="wo-audit-card">
            <header className="wo-audit-card-head"><h3>Pages by section</h3><span>{plural(audit.pageCount, 'page')}</span></header>
            {audit.pageSections.length ? <RankedBars label="Captured pages by section" bars={audit.pageSections.map(section => ({ id: section.id, label: section.label, value: section.count }))} />
              : <p className="wo-audit-empty-chart">No data</p>}
          </article>
          <article className="wo-audit-card wo-audit-card-stack">
            <div className="wo-audit-card-part">
              <header className="wo-audit-card-head"><h3>Link check results</h3><span>{plural(audit.linkTotal, 'target')}</span></header>
              <SegmentedBar label="Link status distribution" parts={toParts(audit.linkDistribution)} />
              <div className="wo-audit-card-links">
                <button type="button" className="wo-audit-link" onClick={() => onOpenNote(notePath('_link-health.md'))}>Open link report <ArrowUpRight size={12} aria-hidden="true" /></button>
                {audit.linkPending > 0 && onContinueLinks && <button type="button" className="wo-audit-link" onClick={onContinueLinks}>Check remaining {formatCount(audit.linkPending)} <ArrowUpRight size={12} aria-hidden="true" /></button>}
              </div>
            </div>
            <div className="wo-audit-card-part">
              <header className="wo-audit-card-head"><h3>Media inventory</h3><span>{plural(audit.resourceCount, 'resource')}</span></header>
              <SegmentedBar label="Resource download states" parts={toParts(audit.mediaDistribution)} />
            </div>
          </article>
        </div>

        <section className="wo-audit-inbox" id="wo-audit-findings" aria-label="Recorded findings inbox">
          <header className="wo-audit-inbox-head">
            <h2>Findings <span>{plural(audit.findings.length, 'group')}</span></h2>
            <p className="wo-audit-filter-count" role="status">{filtered.length} shown, {plural(shownTargets, 'affected item')}{query && ` matching "${query}"`}</p>
          </header>
          <div className="wo-audit-toolbar">
            <label className="wo-audit-search"><Search size={14} aria-hidden="true" /><span className="wo-audit-sr-only">Search recorded findings and affected URLs</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search findings or URLs" /></label>
            <div className="wo-audit-categories" role="group" aria-label="Filter findings by category">
              <button type="button" aria-pressed={category === 'all'} onClick={() => setCategory('all')}>All <span>{audit.findings.length}</span></button>
              {visibleCategories.map(item => <button key={item.id} type="button" aria-pressed={category === item.id} onClick={() => setCategory(item.id)}>{item.label} <span>{categoryCounts.get(item.id)?.groups ?? 0}</span></button>)}
            </div>
          </div>
          {filtered.length ? TONES.map(tone => {
            const groups = filtered.filter(group => group.tone === tone.id);
            if (!groups.length) return null;
            const capped = !expandedTones.has(tone.id) && groups.length > GROUP_ROW_LIMIT + 2;
            return <div key={tone.id} className={`wo-audit-group is-${tone.id}`} id={`wo-audit-group-${tone.id}`}>
              <h3>{tone.title} <span>{groups.length}</span></h3>
              <div className="wo-audit-findings">{(capped ? groups.slice(0, GROUP_ROW_LIMIT) : groups).map(group => <FindingRow key={`${manifest.siteId}:${group.id}:${query}`} group={group} siteId={manifest.siteId} onInspectPage={onInspectPage} onOpenNote={onOpenNote} onOpenExternalUrl={onOpenExternalUrl} />)}</div>
              {capped && <button type="button" className="wo-audit-link wo-audit-more-rows" onClick={() => setExpandedTones(current => new Set(current).add(tone.id))}>Show {groups.length - GROUP_ROW_LIMIT} more {tone.title.toLowerCase()}</button>}
            </div>;
          }) : <div className="wo-audit-empty">
            <h3>{audit.findings.length ? 'No matching findings' : hasObservations ? 'No findings recorded' : 'No data'}</h3>
            <p>{audit.findings.length ? 'Try another category or search term.' : 'This capture contains no recorded findings for these signals.'}</p>
            {(query || category !== 'all') && <button type="button" className="wo-audit-link" onClick={() => { setQuery(''); setCategory('all'); }}>Clear filters</button>}
          </div>}
        </section>

        <div className="wo-audit-more">
          {audit.headers && (audit.headers.present.length > 0 || audit.headers.missing.length > 0) && <Disclosure summary="Homepage response headers" count={audit.headers.present.length + audit.headers.missing.length}>
            <KeyValueList rows={[
              ...audit.headers.present.map(header => ({ label: header, value: 'Present', status: 'good' as const })),
              ...audit.headers.missing.map(header => ({ label: header, value: 'Not observed', status: 'warning' as const })),
            ]} />
          </Disclosure>}
          {audit.mediaTypes.length > 0 && <Disclosure summary="Resource types" count={audit.mediaTypes.length}>
            <KeyValueList rows={audit.mediaTypes.map(type => ({ label: type.label, value: formatCount(type.count) }))} />
          </Disclosure>}
          {(manifest.captureFindings?.length ?? 0) > 0 && <Disclosure summary="Broken resources found while capturing" count={manifest.captureFindings!.length}>
            <ul className="wo-audit-plain-list">{manifest.captureFindings!.map((finding, index) => <li key={index}>{finding}</li>)}</ul>
          </Disclosure>}
          {(manifest.captureWarnings?.length ?? 0) > 0 && <Disclosure summary="Capture warnings" count={manifest.captureWarnings!.length}>
            <ul className="wo-audit-plain-list">{manifest.captureWarnings!.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
          </Disclosure>}
          <ContentAndBrowser manifest={manifest} />
          <Disclosure summary="About these numbers">
            <p className="wo-audit-note">Every number comes from the saved capture. There is no overall health grade.</p>
            <h4>Not assessed</h4>
            <ul className="wo-audit-plain-list">{audit.notAssessed.map(area => <li key={area}>{area}</li>)}</ul>
            <h4>How to read the charts</h4>
            <ul className="wo-audit-plain-list">
              <li>A link response is evidence for check time only. Inconclusive and unchecked targets are not counted as working links.</li>
              <li>Pages by section counts captured internal pages. External domains and undiscovered pages are excluded.</li>
              <li>Intentionally unselected variants and reference only resources are separate from download failures.</li>
              {audit.headers && <li>Headers: {audit.headers.scope.replace(/\.?\s*$/, '.')} Presence checks on one response do not establish site wide security or legal compliance.</li>}
              <li>Browser sample numbers come from one lab load on this machine through the capture proxy. They are not field data or Core Web Vitals. axe-core covers only part of WCAG.</li>
              <li>Trust pages and bylines are recorded as present or absent only. This is not an E-E-A-T judgement.</li>
              <li>Image purpose and decorative use need review. Alt text observations do not establish accessibility conformance.</li>
              {audit.engineFindings && audit.scopeNotes.map(note => <li key={note}>{note}</li>)}
            </ul>
            <button type="button" className="wo-audit-link" onClick={() => onOpenNote(notePath('_dashboard.md'))}>Open capture dashboard <ArrowUpRight size={12} aria-hidden="true" /></button>
          </Disclosure>
        </div>
      </div>
    </div>
  </section>;
}
