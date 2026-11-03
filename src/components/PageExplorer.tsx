import { useMemo } from 'react';
import { ArrowUpRight, FileText, Search, X } from 'lucide-react';
import type { NodeFilter, SiteGraphManifest } from '../types/site';
import { hasNodeIssue, matchesNodeFilter } from '../data/sitePresentation';

interface PageExplorerProps {
  manifest: SiteGraphManifest;
  selectedId: string | null;
  filter: NodeFilter;
  query: string;
  onQuery: (query: string) => void;
  onFilter: (filter: NodeFilter) => void;
  onSelect: (id: string) => void;
  onClose: () => void;
}

export function PageExplorer({ manifest, selectedId, filter, query, onQuery, onFilter, onSelect, onClose }: PageExplorerProps) {
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return manifest.nodes.filter((node) =>
      matchesNodeFilter(node, filter === 'all' ? 'pages' : filter) &&
      (!q || `${node.title} ${node.path} ${node.url}`.toLowerCase().includes(q))
    ).sort((a, b) => {
      if (a.kind === 'home') return -1;
      if (b.kind === 'home') return 1;
      return (a.clickDepth ?? Infinity) - (b.clickDepth ?? Infinity) || a.path.localeCompare(b.path);
    });
  }, [manifest, filter, query]);
  const internalCount = manifest.nodes.filter((n) => n.kind !== 'external-domain').length;
  const issueCount = manifest.nodes.filter(hasNodeIssue).length;
  const externalCount = manifest.nodes.length - internalCount;

  return (
    <aside className="wo-explorer" aria-label="Page explorer" id="wo-page-explorer">
      <div className="wo-explorer-head">
        <div><span className="wo-eyebrow">YOUR CAPTURE</span><h2>Page explorer</h2></div>
        <button type="button" className="wo-icon-btn wo-icon-btn-sm" aria-label="Close page explorer" onClick={onClose}><X size={15} /></button>
      </div>
      <label className="wo-explorer-search">
        <Search size={15} aria-hidden="true" />
        <input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Find a page or URL..." aria-label="Search captured pages" />
        {query && <button type="button" aria-label="Clear page search" onClick={() => onQuery('')}><X size={13} /></button>}
      </label>
      <div className="wo-explorer-tabs" aria-label="Page list filters">
        {([
          ['pages', 'Pages', internalCount], ['issues', 'Flagged', issueCount], ['external', 'Domains', externalCount],
        ] as const).map(([id, label, count]) => (
          <button key={id} type="button" aria-pressed={filter === id || (id === 'pages' && filter === 'all')} onClick={() => onFilter(id)}>{label}<span>{count}</span></button>
        ))}
      </div>
      <div className="wo-explorer-result-count" role="status">
        <span>{rows.length} {rows.length === 1 ? 'result' : 'results'}{filter === 'external' ? ' in saved map' : ''}</span>
        {(query || !['all', 'pages'].includes(filter)) && <button type="button" onClick={() => { onQuery(''); onFilter('all'); }}>Reset</button>}
      </div>
      <div className="wo-page-list">
        {rows.map((node) => (
          <button key={node.id} type="button" className={`wo-page-row ${selectedId === node.id ? 'is-selected' : ''}`} aria-pressed={selectedId === node.id} onClick={() => onSelect(node.id)} title={`${node.title}\n${node.url}`}>
            <span className={`wo-page-row-icon wo-health-${node.health}`}>
              {node.kind === 'external-domain' ? <ArrowUpRight size={15} /> : <FileText size={15} />}
            </span>
            <span className="wo-page-row-copy"><strong>{node.kind === 'home' ? manifest.domain : node.title}</strong><small>{node.path || node.url}</small></span>
            {hasNodeIssue(node) ? <span className="wo-row-status is-warning" aria-label="Flagged page">!</span> : node.kind === 'home' ? <span className="wo-row-home">HOME</span> : null}
          </button>
        ))}
        {rows.length === 0 && <div className="wo-explorer-empty"><Search size={24} /><h3>No matching pages</h3><p>Try another title or URL, or reset the filters.</p><button type="button" onClick={() => { onQuery(''); onFilter('all'); }}>Show captured pages</button></div>}
      </div>
      <div className="wo-explorer-foot"><span className="wo-status-dot" />Saved capture. Select a page to inspect its details.</div>
    </aside>
  );
}
