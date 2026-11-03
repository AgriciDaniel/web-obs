import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, ChevronLeft, ChevronRight, Compass, Shuffle, X } from 'lucide-react';
import type { SiteGraphManifest, SiteNode } from '../types/site';
import { buildDiscoveryStops, chooseDiscoveryNode, discoveryConnections } from '../data/mapDiscovery';
import { mapDiscoveryStyles } from './mapDiscoveryStyles';

interface MapDiscoveryControlsProps {
  manifest: SiteGraphManifest;
  nodes: SiteNode[];
  selectedId: string | null;
  showChromeLinks: boolean;
  onNavigate: (id: string) => void;
  onInspect: (id: string) => void;
}

/** Explicit, untimed exploration. Every stop and link comes from the snapshot. */
export const MapDiscoveryControls = memo(function MapDiscoveryControls({
  manifest, nodes, selectedId, showChromeLinks, onNavigate, onInspect,
}: MapDiscoveryControlsProps) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [visited, setVisited] = useState<Set<string>>(() => new Set());
  const launcherRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const visible = useMemo(() => new Set(nodes.map(node => node.id)), [nodes]);
  const stops = useMemo(() => buildDiscoveryStops(nodes), [nodes]);
  const selected = useMemo(() => nodes.find(node => node.id === selectedId), [nodes, selectedId]);
  const selectedStop = stops.findIndex(stop => stop.node.id === selectedId);
  const index = selectedStop >= 0 ? selectedStop : Math.min(cursor, Math.max(0, stops.length - 1));
  const node = selected ?? stops[index]?.node;
  const stop = selected ? stops.find(item => item.node.id === selected.id) : stops[index];
  const peers = useMemo(() => discoveryConnections(manifest, node?.id ?? null, visible, showChromeLinks),
    [manifest, node?.id, visible, showChromeLinks]);
  const explored = nodes.reduce((count, item) => count + Number(visited.has(item.id)), 0);

  useEffect(() => {
    if (!selectedId || !visible.has(selectedId)) return;
    setVisited(previous => previous.has(selectedId) ? previous : new Set([...previous, selectedId]));
  }, [selectedId, visible]);

  useEffect(() => {
    if (open) closeRef.current?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => { setOpen(false); }, [nodes]);

  if (!nodes.length || !node) return null;

  const navigate = (id: string) => {
    const stopIndex = stops.findIndex(item => item.node.id === id);
    if (stopIndex >= 0) setCursor(stopIndex);
    setVisited(previous => new Set([...previous, id]));
    onNavigate(id);
  };
  const start = () => {
    setOpen(true);
    navigate(stops[0].node.id);
  };
  const step = (direction: number) => {
    const next = (index + direction + stops.length) % stops.length;
    setCursor(next);
    navigate(stops[next].node.id);
  };
  const surprise = () => {
    const next = chooseDiscoveryNode(nodes, visited, selectedId);
    if (!next) return;
    setOpen(true);
    navigate(next.id);
  };
  const close = () => {
    setOpen(false);
    requestAnimationFrame(() => launcherRef.current?.focus({ preventScroll: true }));
  };

  return <div className="wo-discovery-layer">
    <style>{mapDiscoveryStyles}</style>
    {open ? <section className="wo-discovery-card" aria-label="Map discovery" onKeyDown={event => {
      if (event.key === 'Escape') { event.stopPropagation(); close(); }
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        event.stopPropagation();
        step(event.key === 'ArrowLeft' ? -1 : 1);
      }
    }}>
      <div className="wo-discovery-head">
        <Compass size={14} aria-hidden="true" /><span>MAP DISCOVERY</span>
        <small>{explored} / {nodes.length} explored</small>
        <button ref={closeRef} type="button" className="wo-discovery-dismiss" aria-label="Close map discovery" onClick={close}><X size={14} /></button>
      </div>
      <div aria-live="polite" aria-atomic="true">
        <span className="wo-discovery-kicker">{stop?.label ?? 'Make your own trail'}</span>
        <h2 className="wo-discovery-title" title={node.title}>{node.kind === 'home' ? manifest.domain : node.title}</h2>
        <div className="wo-discovery-path" title={node.url}>{node.path || node.url}</div>
        <p className="wo-discovery-description">{stop?.description ?? 'A different corner of your saved map. Follow a captured link and see where it leads.'}</p>
      </div>
      {peers.length > 0 && <div className="wo-discovery-links">
        <span>Follow a captured link</span>
        <div className="wo-discovery-peers">{peers.slice(0, 2).map(peer => {
          const Icon = peer.direction === 'outgoing' ? ArrowUpRight : peer.direction === 'incoming' ? ArrowDownLeft : ArrowLeftRight;
          const direction = peer.direction === 'outgoing' ? 'Links to' : peer.direction === 'incoming' ? 'Linked from' : 'Linked both ways with';
          return <button key={peer.node.id} type="button" className="wo-discovery-peer" title={direction + ' ' + peer.node.title + (peer.anchor ? ': ' + peer.anchor : '')} aria-label={direction + ' ' + peer.node.title} onClick={() => navigate(peer.node.id)}>
            <Icon size={12} aria-hidden="true" /><span>{peer.node.kind === 'home' ? manifest.domain : peer.node.title}</span>
          </button>;
        })}</div>
      </div>}
      <div className="wo-discovery-actions">
        <button type="button" className="wo-discovery-step" aria-label="Previous highlight" title="Previous highlight (left arrow)" disabled={stops.length < 2} onClick={() => step(-1)}><ChevronLeft size={15} /></button>
        <div className="wo-discovery-pagination" aria-label={selectedStop >= 0 ? 'Highlight ' + (index + 1) + ' of ' + stops.length : 'Free exploration'}>
          {stops.map(item => <span key={item.node.id} className={item.node.id === selectedId ? 'is-current' : ''} />)}
        </div>
        <button type="button" className="wo-discovery-step" aria-label="Next highlight" title="Next highlight (right arrow)" disabled={stops.length < 2} onClick={() => step(1)}><ChevronRight size={15} /></button>
        <button type="button" className="wo-discovery-inspect" aria-label="Inspect this page" onClick={() => onInspect(node.id)}><ArrowUpRight size={12} aria-hidden="true" />Inspect</button>
        <button type="button" className="wo-discovery-random" aria-label="Surprise me with another stop" disabled={nodes.length < 2} onClick={surprise}><Shuffle size={12} aria-hidden="true" /><span>Surprise me</span></button>
      </div>
    </section> : <div className="wo-discovery-launcher">
      <button ref={launcherRef} type="button" className="wo-discovery-start" aria-label="Explore map highlights" aria-expanded={false} onClick={start}><Compass size={16} aria-hidden="true" /><span>Explore this map</span><small>{stops.length} highlights</small></button>
      <button type="button" className="wo-discovery-shuffle" title="Visit a different captured place" aria-label="Surprise me with another stop" disabled={nodes.length < 2} onClick={surprise}><Shuffle size={15} aria-hidden="true" /></button>
    </div>}
  </div>;
});
