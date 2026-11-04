import React, { useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, ChevronRight, ExternalLink, FileText, Globe, X } from 'lucide-react';
import type { EngineFindingTone, SiteGraphManifest, SiteNode } from '../types/site';
import { captureDate } from '../data/sitePresentation';
import { BrowserSamplePanel, PageChecksSection, browserSampleFor, issueLabel, pageCheckNotes } from './PageChecksSection';
import { Disclosure, EmptyState, Section, StatRow, StatTile, StatusPill, Tabs, formatCount, type Status, type TabItem } from './ui';
import '../styles/drawers.css';

interface InspectorDrawerProps {
  manifest: SiteGraphManifest;
  node: SiteNode;
  onClose: () => void;
  onSelectAndFly: (nodeId: string) => void;
  onOpenNote: (obsidianPath: string) => void;
  resolveAssetUrl?: (vaultRelativePath: string) => string | null;
  onOpenExternalUrl: (url: string) => void;
}

const HEALTH: Record<SiteNode['health'], { label: string; status: Status }> = {
  home: { label: 'Homepage', status: 'info' },
  hub: { label: 'Section hub', status: 'good' },
  healthy: { label: 'Live page', status: 'good' },
  orphan: { label: 'Orphan: in sitemap, no inlinks', status: 'warning' },
  unlisted: { label: 'Not in sitemap', status: 'warning' },
  redirect: { label: 'Redirect', status: 'warning' },
  broken: { label: 'Broken link', status: 'critical' },
  unavailable: { label: 'Unavailable or incomplete', status: 'critical' },
  external: { label: 'External domain', status: 'neutral' },
};

const TONE_GROUPS: Array<{ tone: EngineFindingTone; title: string }> = [
  { tone: 'attention', title: 'Needs attention' },
  { tone: 'review', title: 'Worth reviewing' },
  { tone: 'coverage', title: 'Coverage gaps' },
];

const urlKey = (url: string) => url.replace(/\/+$/, '').toLowerCase();

interface LinkItem { key: string; peer: SiteNode; anchor: string; nav: boolean }

const LINK_CAP = 10;

function LinkList({ items, icon, label, onPick, domain }: { items: LinkItem[]; icon: React.ReactNode; label: (peer: SiteNode) => string; onPick: (id: string) => void; domain: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, LINK_CAP);
  return <>
    <ul className="wo-dr-linklist">
      {shown.map(({ key, peer, anchor, nav }) => <li key={key}>
        <button type="button" className="wo-dr-link" onClick={() => onPick(peer.id)} title={anchor ? `${peer.url}\nAnchor: ${anchor}` : peer.url}>
          {icon}
          <span className="wo-dr-link-main">{peer.kind === 'home' ? domain : label(peer)}</span>
          {nav && <span className="wo-dr-tag">nav</span>}
        </button>
      </li>)}
    </ul>
    {items.length > LINK_CAP && <button type="button" className="wo-dr-more" onClick={() => setAll(!all)}>{all ? 'Show fewer' : `Show all ${items.length}`}</button>}
  </>;
}

export const InspectorDrawer: React.FC<InspectorDrawerProps> = ({
  manifest,
  node,
  onClose,
  onSelectAndFly,
  onOpenNote,
  resolveAssetUrl,
  onOpenExternalUrl,
}) => {
  const nodeById = useMemo(() => new Map(manifest.nodes.map((n) => [n.id, n])), [manifest.nodes]);

  const { incoming, outgoingInternal, outgoingExternal } = useMemo(() => {
    const inc: LinkItem[] = [];
    const outInt: LinkItem[] = [];
    const outExt: LinkItem[] = [];
    manifest.edges.forEach((e, index) => {
      if (e.kind === 'sitemap-hierarchy') return;
      if (e.target === node.id) {
        const peer = nodeById.get(e.source);
        if (peer) inc.push({ key: `${e.id}-${index}`, peer, anchor: e.anchor ?? '', nav: e.kind === 'internal-chrome' });
      }
      if (e.source === node.id) {
        const peer = nodeById.get(e.target);
        if (!peer) return;
        (e.kind === 'external' ? outExt : outInt).push({ key: `${e.id}-${index}`, peer, anchor: e.anchor ?? '', nav: e.kind === 'internal-chrome' });
      }
    });
    return { incoming: inc, outgoingInternal: outInt, outgoingExternal: outExt };
  }, [manifest.edges, node.id, nodeById]);

  const pageResources = (manifest.resources ?? []).filter((resource) => resource.references.some((reference) => reference.pageUrl === node.url));
  const sample = browserSampleFor(manifest, node);

  const issues = useMemo(() => (node.seoIssues ?? []).map((issue) => {
    const slug = issue.replace(/\s*\(\d+\)$/, '');
    const entry = manifest.issueCatalog?.[slug];
    return { id: issue, label: issueLabel(manifest, issue), tone: (entry?.tone ?? 'review') as EngineFindingTone, explanation: entry?.explanation };
  }), [manifest, node.seoIssues]);

  const siteFindings = useMemo(() => {
    const key = urlKey(node.url);
    return (manifest.audit?.findings ?? []).flatMap((finding) => {
      const target = finding.targets.find((t) => urlKey(t.url) === key);
      return target ? [{ id: finding.id, title: finding.title, tone: finding.tone, detail: target.detail, explanation: finding.explanation }] : [];
    });
  }, [manifest.audit, node.url]);

  const isExternal = node.kind === 'external-domain';
  const health = HEALTH[node.health];
  const attention = issues.filter((i) => i.tone === 'attention').length + siteFindings.filter((f) => f.tone === 'attention').length;
  const issueTotal = issues.length + siteFindings.length;
  const linkTotal = incoming.length + outgoingInternal.length + outgoingExternal.length + pageResources.length;

  const notes = [
    `From the saved capture on ${captureDate(manifest.capturedAt)}.`,
    ...(node.authorityScore !== undefined ? [`Link score ${node.authorityScore} of 100 is a relative internal link-graph heuristic, not a search engine metric.`] : []),
    ...(isExternal ? [] : pageCheckNotes(manifest, node)),
  ];

  const issuesTab = issueTotal === 0 ? <EmptyState>No issues recorded for this page.</EmptyState> : <>
    {TONE_GROUPS.map(({ tone, title }) => {
      const own = issues.filter((i) => i.tone === tone);
      if (!own.length) return null;
      return <Section key={tone} title={title} aside={formatCount(own.length)}>
        <ul className="wo-dr-issues">{own.map((issue) => <li key={issue.id}>
          {issue.explanation ? <Disclosure summary={<span className="wo-dr-issue-title">{tone === 'attention' && <StatusPill status="critical" label="Fix" />}{issue.label}</span>}>
            <p className="wo-ui-note">{issue.explanation}</p>
          </Disclosure> : <span className="wo-dr-issue-plain">{issue.label}</span>}
        </li>)}</ul>
      </Section>;
    })}
    {siteFindings.length > 0 && <Section title="Site findings that include this page" aside={formatCount(siteFindings.length)}>
      <ul className="wo-dr-issues">{siteFindings.map((finding) => <li key={finding.id}>
        <Disclosure summary={<span className="wo-dr-issue-title">{finding.tone === 'attention' && <StatusPill status="critical" label="Fix" />}{finding.title}</span>}>
          {finding.detail && <p className="wo-dr-line">{finding.detail}</p>}
          <p className="wo-ui-note">{finding.explanation}</p>
        </Disclosure>
      </li>)}</ul>
    </Section>}
  </>;

  const linksTab = linkTotal === 0 ? <EmptyState>No links recorded for this page.</EmptyState> : <div className="wo-dr-stack">
    {incoming.length > 0 && <Disclosure summary="Incoming links" count={incoming.length} defaultOpen>
      <LinkList items={incoming} icon={<ArrowDownLeft size={13} className="wo-link-icon-in" aria-hidden="true" />} label={(peer) => peer.path} onPick={onSelectAndFly} domain={manifest.domain} />
    </Disclosure>}
    {outgoingInternal.length > 0 && <Disclosure summary="Outgoing internal" count={outgoingInternal.length}>
      <LinkList items={outgoingInternal} icon={<ArrowUpRight size={13} className="wo-link-icon-out" aria-hidden="true" />} label={(peer) => peer.path} onPick={onSelectAndFly} domain={manifest.domain} />
    </Disclosure>}
    {outgoingExternal.length > 0 && <Disclosure summary="External domains" count={outgoingExternal.length}>
      <LinkList items={outgoingExternal} icon={<Globe size={13} className="wo-link-icon-ext" aria-hidden="true" />} label={(peer) => peer.title} onPick={onSelectAndFly} domain={manifest.domain} />
    </Disclosure>}
    {pageResources.length > 0 && <details className="wo-ui-disclosure wo-resource-details">
      <summary><ChevronRight size={13} className="wo-ui-disclosure-chevron" aria-hidden="true" /><span>Media and resources</span><span className="wo-ui-count">{formatCount(pageResources.length)}</span></summary>
      <div className="wo-ui-disclosure-body">
        <ul className="wo-dr-linklist">{pageResources.map((resource) => <li key={resource.id}>
          <button type="button" className="wo-dr-link" onClick={() => onOpenExternalUrl(resource.url)} title={resource.url}>
            <span className="wo-dr-tag">{resource.type}</span>
            <span className="wo-dr-link-main">{resource.references.find((reference) => reference.pageUrl === node.url && reference.label)?.label || resource.url.split('/').at(-1) || resource.url}</span>
            <span className="wo-dr-link-aside">{resource.localFileStatus === 'preserved-local-edits' ? 'Local edit kept' : resource.checkStatus || resource.downloadState || 'Reference'}</span>
          </button>
        </li>)}</ul>
      </div>
    </details>}
  </div>;

  const tabs: TabItem[] = isExternal ? [] : [
    { id: 'issues', label: 'Issues', badge: issueTotal, content: issuesTab },
    { id: 'checks', label: 'Checks', content: <PageChecksSection manifest={manifest} node={node} /> },
    { id: 'links', label: 'Links', badge: linkTotal, content: linksTab },
    ...(sample ? [{ id: 'browser', label: 'Browser', content: <BrowserSamplePanel manifest={manifest} sample={sample} onOpenNote={onOpenNote} resolveAssetUrl={resolveAssetUrl} /> }] : []),
  ];

  return (
    <aside className="wo-inspector wo-dr" aria-label="Page Inspector">
      <header className="wo-dr-head">
        <div className="wo-dr-head-text">
          <div className="wo-dr-badges">
            <StatusPill status={health.status} label={health.label} />
            {!isExternal && <span className="wo-dr-meta">{node.statusCode > 0 ? `HTTP ${node.statusCode}` : 'No HTTP response'}{node.responseTimeMs ? ` · ${formatCount(node.responseTimeMs)} ms` : ''}</span>}
          </div>
          <h2 className="wo-dr-title">{node.title}</h2>
          <span className="wo-dr-sub wo-dr-mono" title={node.url}>{node.kind === 'home' ? `${manifest.domain} (/)` : node.path}</span>
        </div>
        <button type="button" className="wo-icon-btn wo-icon-btn-sm" onClick={onClose} title="Close inspector (Esc)" aria-label="Close inspector">
          <X size={15} />
        </button>
      </header>

      {node.error && <p className="wo-dr-alert" role="status">{node.error}</p>}
      {node.noteStatus === 'preserved-local-edits' && <p className="wo-dr-alert" role="status">Your existing note was preserved. A fresh generated version is listed in the recapture report.</p>}

      <div className="wo-dr-actions" role="group" aria-label="Page actions">
        <button type="button" className="wo-btn-primary wo-btn-xs" onClick={() => onOpenNote(node.obsidianPath)}>
          <FileText size={13} aria-hidden="true" /><span>Open Note</span>
        </button>
        <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={() => onOpenExternalUrl(node.url)} title={node.url}>
          <ExternalLink size={13} aria-hidden="true" /><span>Live URL</span>
        </button>
      </div>

      {isExternal ? <>
        {node.metaDescription && <p className="wo-dr-line">{node.metaDescription}</p>}
        {node.externalUrlsSample && node.externalUrlsSample.length > 0 && <Section title="Linked URLs" aside={formatCount(node.externalUrlsSample.length)}>
          <ul className="wo-dr-linklist">{node.externalUrlsSample.slice(0, 8).map((url) => <li key={url}>
            <button type="button" className="wo-dr-link" onClick={() => onOpenExternalUrl(url)} title={url}><Globe size={13} aria-hidden="true" /><span className="wo-dr-link-main">{url.replace(/^https?:\/\//, '')}</span></button>
          </li>)}</ul>
        </Section>}
        {incoming.length > 0 && <Disclosure summary="Linked from" count={incoming.length} defaultOpen>
          <LinkList items={incoming} icon={<ArrowDownLeft size={13} className="wo-link-icon-in" aria-hidden="true" />} label={(peer) => peer.path} onPick={onSelectAndFly} domain={manifest.domain} />
        </Disclosure>}
      </> : <>
        <StatRow label="Page numbers">
          <StatTile label="Words" value={formatCount(node.wordCount)} hint={node.readingTimeMin ? `${node.readingTimeMin} min read` : undefined} />
          <StatTile label="Click depth" value={node.clickDepth !== null ? String(node.clickDepth) : 'None'} hint={node.clickDepth === null ? 'Not reached by links' : node.clickDepth === 0 ? 'Homepage' : 'Clicks from home'} />
          <StatTile label="Inlinks" value={formatCount(incoming.length)} hint={node.authorityScore !== undefined ? `Link score ${node.authorityScore}` : undefined} />
          <StatTile label="Issues" value={formatCount(issueTotal)} hint={attention ? `${attention} need attention` : undefined} status={attention ? 'critical' : undefined} />
        </StatRow>
        <Tabs label="Page inspector sections" initial={issueTotal ? 'issues' : 'checks'} tabs={tabs} />
      </>}

      <div className="wo-dr-about">
        <Disclosure summary="About these numbers">
          <ul className="wo-dr-list">{notes.map((note) => <li key={note}>{note}</li>)}</ul>
        </Disclosure>
      </div>
    </aside>
  );
};
