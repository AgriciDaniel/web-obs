import { useMemo } from 'react';
import { ArrowUpRight, FileText, Search, X, XCircle } from 'lucide-react';
import type { NodeFilter, SiteGraphManifest, SiteNode } from '../types/site';
import { matchesNodeFilter } from '../data/sitePresentation';

interface PageExplorerProps {
  manifest: SiteGraphManifest;
  attention: ReadonlySet<string>;
  selectedId: string | null;
  filter: NodeFilter;
  query: string;
  onQuery: (query: string) => void;
  onFilter: (filter: NodeFilter) => void;
  onSelect: (id: string) => void;
  onClose: () => void;
}

export function PageExplorer({ manifest, attention, selectedId, filter, query, onQuery, onFilter, onSelect, onClose }: PageExplorerProps) {
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = (node: SiteNode) =>
      filter === 'issues' ? attention.has(node.id) : matchesNodeFilter(node, filter === 'all' ? 'pages' : filter);
    return manifest.nodes.filter((node) => matches(node) &&
      (!q || `${node.title} ${node.path} ${node.url}`.toLowerCase().includes(q))
    ).sort((a, b) => {
      if (a.kind === 'home') return -1;
      if (b.kind === 'home') return 1;
      return Number(attention.has(b.id)) - Number(attention.has(a.id)) ||
        (a.clickDepth ?? Infinity) - (b.clickDepth ?? Infinity) || a.path.localeCompare(b.path);
    });
  }, [manifest, attention, filter, query]);
  const internalCount = manifest.nodes.filter((n) => n.kind !== 'external-domain').length;
  const externalCount = manifest.nodes.length - internalCount;
  const tabs = ([
    ['pages', 'Pages', internalCount], ['issues', 'Needs attention', attention.size], ['external', 'Domains', externalCount],
  ] as const).filter(([id, , count]) => count > 0 || filter === id);

  return (
    <aside className="wo-explorer" aria-label="Page explorer" id="wo-page-explorer">
      <div className="wo-explorer-head">
        <h2>Pages</h2>
        <button type="button" className="wo-icon-btn wo-icon-btn-sm" aria-label="Close page explorer" onClick={onClose}><X size={15} /></button>
      </div>
      <label className="wo-explorer-search">
        <Search size={14} aria-hidden="true" />
        <input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Find a page or URL" aria-label="Search captured pages" />
        {query && <button type="button" aria-label="Clear page search" onClick={() => onQuery('')}><X size={13} /></button>}
      </label>
      <div className="wo-explorer-tabs" aria-label="Page list filters">
        {tabs.map(([id, label, count]) => (
          <button key={id} type="button" aria-pressed={filter === id || (id === 'pages' && filter === 'all')} onClick={() => onFilter(id)}>{label}<span>{count}</span></button>
        ))}
      </div>
      <div className="wo-explorer-result-count" role="status">
        <span>{rows.length} {rows.length === 1 ? 'result' : 'results'}</span>
        {(query || !['all', 'pages'].includes(filter)) && <button type="button" onClick={() => { onQuery(''); onFilter('all'); }}>Reset</button>}
      </div>
      <div className="wo-page-list">
        {rows.map((node) => {
          const flagged = attention.has(node.id);
          return (
            <button key={node.id} type="button" className={`wo-page-row ${selectedId === node.id ? 'is-selected' : ''}`} aria-pressed={selectedId === node.id} onClick={() => onSelect(node.id)} title={`${node.title}\n${node.url}`}>
              <span className={`wo-page-row-icon wo-health-${node.health}`}>
                {node.kind === 'external-domain' ? <ArrowUpRight size={14} /> : <FileText size={14} />}
              </span>
              <span className="wo-page-row-copy"><strong>{node.kind === 'home' ? manifest.domain : node.title}</strong><small>{node.path || node.url}</small></span>
              {flagged ? <span className="wo-row-status is-critical" aria-label="Needs attention" title="Needs attention"><XCircle size={13} aria-hidden="true" /></span>
                : node.kind === 'home' ? <span className="wo-row-home">Home</span> : null}
            </button>
          );
        })}
        {rows.length === 0 && <div className="wo-explorer-empty"><h3>No matching pages</h3><p>Try another title or URL.</p><button type="button" onClick={() => { onQuery(''); onFilter('all'); }}>Show all pages</button></div>}
      </div>
    </aside>
  );
}
