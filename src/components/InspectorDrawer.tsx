import React, { useMemo } from 'react';
import {
  ArrowDownLeft,
  ArrowUpRight,
  ExternalLink,
  FileText,
  Globe,
  X,
} from 'lucide-react';
import type { SiteGraphManifest, SiteNode } from '../types/site';
import { captureDate } from '../data/sitePresentation';

interface InspectorDrawerProps {
  manifest: SiteGraphManifest;
  node: SiteNode;
  onClose: () => void;
  onSelectAndFly: (nodeId: string) => void;
  onOpenNote: (obsidianPath: string) => void;
  onOpenExternalUrl: (url: string) => void;
}

const HEALTH_LABEL: Record<SiteNode['health'], string> = {
  home: 'Homepage',
  hub: 'Section Hub',
  healthy: 'Live Page',
  orphan: 'Orphan (In Sitemap, 0 Inlinks)',
  unlisted: 'Unlisted (Not in Sitemap)',
  redirect: 'Redirect',
  broken: 'Broken Link',
  unavailable: 'Unavailable or incomplete',
  external: 'External Domain',
};

export const InspectorDrawer: React.FC<InspectorDrawerProps> = ({
  manifest,
  node,
  onClose,
  onSelectAndFly,
  onOpenNote,
  onOpenExternalUrl,
}) => {
  const nodeById = useMemo(
    () => new Map(manifest.nodes.map((n) => [n.id, n])),
    [manifest.nodes]
  );

  const pageResources = (manifest.resources ?? []).filter(resource => resource.references.some(reference => reference.pageUrl === node.url));

  const incoming = useMemo(() => {
    const items: Array<{ peer: SiteNode; anchor: string; kind: string }> = [];
    for (const e of manifest.edges) {
      if (e.target !== node.id || e.kind === 'sitemap-hierarchy') continue;
      const peer = nodeById.get(e.source);
      if (peer) {
        items.push({ peer, anchor: e.anchor ?? '', kind: e.kind });
      }
    }
    return items;
  }, [manifest.edges, node.id, nodeById]);

  const outgoingInternal = useMemo(() => {
    const items: Array<{ peer: SiteNode; anchor: string; kind: string }> = [];
    for (const e of manifest.edges) {
      if (
        e.source !== node.id ||
        e.kind === 'external' ||
        e.kind === 'sitemap-hierarchy'
      ) {
        continue;
      }
      const peer = nodeById.get(e.target);
      if (peer) {
        items.push({ peer, anchor: e.anchor ?? '', kind: e.kind });
      }
    }
    return items;
  }, [manifest.edges, node.id, nodeById]);

  const outgoingExternal = useMemo(() => {
    const items: Array<{ peer: SiteNode; anchor: string; targetUrl?: string }> = [];
    for (const e of manifest.edges) {
      if (e.source !== node.id || e.kind !== 'external') continue;
      const peer = nodeById.get(e.target);
      if (peer) {
        items.push({ peer, anchor: e.anchor ?? '', targetUrl: e.targetUrl });
      }
    }
    return items;
  }, [manifest.edges, node.id, nodeById]);

  const isExternal = node.kind === 'external-domain';

  return (
    <aside className="wo-inspector" aria-label="Page Inspector">
      <div className="wo-inspector-head">
        <div className="wo-inspector-badges">
          <span className={`wo-badge wo-badge-${node.health}`}>
            {HEALTH_LABEL[node.health]}
          </span>
          {!isExternal && (
            <span className="wo-badge wo-badge-mono">{node.statusCode > 0 ? `HTTP ${node.statusCode}` : 'No HTTP response'}</span>
          )}
          {!isExternal && node.responseTimeMs !== undefined && node.responseTimeMs > 0 && (
            <span className="wo-badge wo-badge-mono">{node.responseTimeMs} ms</span>
          )}
        </div>
        <button
          type="button"
          className="wo-icon-btn wo-icon-btn-sm"
          onClick={onClose}
          title="Close inspector (Esc)"
          aria-label="Close inspector"
        >
          <X size={15} />
        </button>
      </div>

      <h2 className="wo-inspector-title">{node.title}</h2>
      <div className="wo-inspector-path">
        {node.kind === 'home' ? `${manifest.domain} (/)` : node.path}
      </div>
      <p className="wo-evidence-note">From the saved capture on {captureDate(manifest.capturedAt)}.</p>

      {node.error && <p className="wo-evidence-note" role="status">{node.error}</p>}
      {node.noteStatus === 'preserved-local-edits' && <p className="wo-evidence-note" role="status">Your existing note was preserved. A fresh generated version is listed in the recapture report.</p>}
      {node.authorityScore !== undefined && <p className="wo-evidence-note">Relative internal link score: {node.authorityScore}/100. A local link-graph heuristic.</p>}

      <div className="wo-inspector-actions">
        <button
          type="button"
          className="wo-btn-primary"
          onClick={() => onOpenNote(node.obsidianPath)}
        >
          <FileText size={14} />
          <span>Open Note</span>
        </button>
        <button
          type="button"
          className="wo-btn-secondary"
          onClick={() => onOpenExternalUrl(node.url)}
          title={node.url}
        >
          <ExternalLink size={14} />
          <span>Live URL</span>
        </button>
      </div>

      {pageResources.length > 0 && <details className="wo-inspector-section wo-resource-details">
        <summary className="wo-section-title">Media and resources ({pageResources.length})</summary>
        <div className="wo-ext-sample-list">{pageResources.map((resource) => <button key={resource.id} type="button" className="wo-link-row" onClick={() => onOpenExternalUrl(resource.url)} title={resource.url}>
          <span className="wo-link-row-main">{resource.type}: {resource.references.find((reference) => reference.pageUrl === node.url && reference.label)?.label || resource.url.split('/').at(-1) || resource.url}</span>
          <span className="wo-badge wo-badge-mono">{resource.localFileStatus === 'preserved-local-edits' ? 'Local edit kept' : resource.checkStatus || resource.downloadState || 'Reference'}</span>
        </button>)}</div>
      </details>}

      {!isExternal ? (
        <>
          <div className="wo-metrics-grid">
            <div className="wo-metric-card">
              <span className="wo-metric-label">Click Depth</span>
              <span className="wo-metric-val">
                {node.clickDepth !== null ? `D${node.clickDepth}` : 'Orphan'}
              </span>
            </div>
            <div className="wo-metric-card">
              <span className="wo-metric-label">Sitemap</span>
              <span className="wo-metric-val">{node.inSitemap ? 'Yes' : 'No'}</span>
            </div>
            <div className="wo-metric-card">
              <span className="wo-metric-label">Words</span>
              <span className="wo-metric-val">
                {node.wordCount.toLocaleString()}
                {node.readingTimeMin ? ` · ${node.readingTimeMin}m` : ''}
              </span>
            </div>
            <div className="wo-metric-card">
              <span className="wo-metric-label">Local Media</span>
              <span className="wo-metric-val">
                {node.localImagesCount}/{node.imagesCount}
              </span>
            </div>
          </div>

          {node.seoIssues && node.seoIssues.length > 0 && (
            <div className="wo-inspector-section">
              <div className="wo-section-title">
                SEO Audit Signals ({node.seoIssues.length})
              </div>
              <div className="wo-schema-row">
                {node.seoIssues.map((issue) => (
                  <span key={issue} className="wo-schema-chip wo-chip-warn">
                    {issue.replace(/-/g, ' ')}
                  </span>
                ))}
              </div>
            </div>
          )}

          {Boolean(
            (node.tablesCount ?? 0) > 0 ||
              (node.codeBlocksCount ?? 0) > 0 ||
              (node.videosCount ?? 0) > 0 ||
              (node.formsCount ?? 0) > 0
          ) && (
            <div className="wo-inspector-section">
              <div className="wo-section-title">Extracted Structure</div>
              <div className="wo-schema-row">
                {(node.tablesCount ?? 0) > 0 && (
                  <span className="wo-schema-chip">{node.tablesCount} table(s)</span>
                )}
                {(node.codeBlocksCount ?? 0) > 0 && (
                  <span className="wo-schema-chip">
                    {node.codeBlocksCount} code block(s)
                  </span>
                )}
                {(node.videosCount ?? 0) > 0 && (
                  <span className="wo-schema-chip">{node.videosCount} video(s)</span>
                )}
                {(node.formsCount ?? 0) > 0 && (
                  <span className="wo-schema-chip">{node.formsCount} form(s)</span>
                )}
              </div>
            </div>
          )}

          {(node.metaDescription ||
            node.h1.length > 0 ||
            node.schemaTypes.length > 0 ||
            node.author ||
            node.publishedDate) && (
            <div className="wo-inspector-section">
              <div className="wo-section-title">Page Metadata</div>
              {node.h1.length > 0 && (
                <div className="wo-meta-block">
                  <span className="wo-meta-key">H1</span>
                  <span className="wo-meta-text">{node.h1[0]}</span>
                </div>
              )}
              {node.metaDescription && (
                <div className="wo-meta-block">
                  <span className="wo-meta-key">
                    Description ({node.metaDescription.length} chars)
                  </span>
                  <span className="wo-meta-text">{node.metaDescription}</span>
                </div>
              )}
              {node.canonical && <div className="wo-meta-block"><span className="wo-meta-key">Declared canonical</span><span className="wo-meta-text wo-break-url">{node.canonical}</span></div>}
              {node.metaRobots && <div className="wo-meta-block"><span className="wo-meta-key">Page robots directive</span><span className="wo-meta-text">{node.metaRobots}</span></div>}
              {(node.author || node.publishedDate || node.lang) && (
                <div className="wo-meta-key">
                  {[
                    node.author ? `Author: ${node.author}` : '',
                    node.publishedDate ? `Published: ${node.publishedDate.slice(0, 10)}` : '',
                    node.lang ? `Lang: ${node.lang}` : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
              )}
              {node.schemaTypes.length > 0 && (
                <div className="wo-schema-row">
                  {node.schemaTypes.map((st) => (
                    <span key={st} className="wo-schema-chip">
                      {st}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="wo-inspector-section">
          <div className="wo-section-title">External Satellite Summary</div>
          <p className="wo-meta-text">{node.metaDescription}</p>
          {node.externalUrlsSample && node.externalUrlsSample.length > 0 && (
            <div className="wo-ext-sample-list">
              {node.externalUrlsSample.slice(0, 6).map((u) => (
                <button
                  key={u}
                  type="button"
                  className="wo-link-row"
                  onClick={() => onOpenExternalUrl(u)}
                >
                  <Globe size={12} />
                  <span className="wo-link-row-main">{u}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {incoming.length > 0 && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            Incoming Links ({incoming.length})
          </div>
          <div className="wo-link-list">
            {incoming.slice(0, 24).map(({ peer, anchor, kind }, idx) => (
              <button
                key={`${peer.id}-${idx}`}
                type="button"
                className="wo-link-row"
                onClick={() => onSelectAndFly(peer.id)}
              >
                <ArrowDownLeft size={13} className="wo-link-icon-in" />
                <span className="wo-link-row-main">
                  {peer.kind === 'home' ? manifest.domain : peer.path}
                </span>
                {anchor && <span className="wo-link-row-sub">{anchor}</span>}
                {kind === 'internal-chrome' && (
                  <span className="wo-mini-tag">nav</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {outgoingInternal.length > 0 && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            Outgoing Internal Links ({outgoingInternal.length})
          </div>
          <div className="wo-link-list">
            {outgoingInternal.slice(0, 24).map(({ peer, anchor, kind }, idx) => (
              <button
                key={`${peer.id}-${idx}`}
                type="button"
                className="wo-link-row"
                onClick={() => onSelectAndFly(peer.id)}
              >
                <ArrowUpRight size={13} className="wo-link-icon-out" />
                <span className="wo-link-row-main">
                  {peer.kind === 'home' ? manifest.domain : peer.path}
                </span>
                {anchor && <span className="wo-link-row-sub">{anchor}</span>}
                {kind === 'internal-chrome' && (
                  <span className="wo-mini-tag">nav</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {outgoingExternal.length > 0 && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            Outgoing External Links ({outgoingExternal.length})
          </div>
          <div className="wo-link-list">
            {outgoingExternal.slice(0, 24).map(({ peer, anchor }, idx) => (
              <button
                key={`${peer.id}-${idx}`}
                type="button"
                className="wo-link-row"
                onClick={() => onSelectAndFly(peer.id)}
              >
                <Globe size={13} className="wo-link-icon-ext" />
                <span className="wo-link-row-main">{peer.title}</span>
                {anchor && <span className="wo-link-row-sub">{anchor}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
};
