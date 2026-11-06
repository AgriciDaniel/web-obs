import type { SiteGraphManifest, SiteNode } from '../types/site';
import { hasNodeIssue } from './sitePresentation';

export interface DiscoveryStop {
  node: SiteNode;
  label: string;
  description: string;
}

export interface DiscoveryConnection {
  node: SiteNode;
  direction: 'incoming' | 'outgoing' | 'both';
  anchor: string;
}

/** Highlights describe retained observations, never a new site-wide audit. */
export function buildDiscoveryStops(nodes: readonly SiteNode[]): DiscoveryStop[] {
  const stops: DiscoveryStop[] = [];
  const seen = new Set<string>();
  const pages = nodes.filter(node => node.kind !== 'external-domain');
  const add = (node: SiteNode | undefined, label: string, description: string) => {
    if (!node || seen.has(node.id)) return;
    seen.add(node.id);
    stops.push({ node, label, description });
  };
  const rank = (score: (node: SiteNode) => number, candidates = pages) =>
    [...candidates].sort((a, b) => score(b) - score(a) || a.path.localeCompare(b.path)).find(node => !seen.has(node.id));
  add(pages.find(node => node.kind === 'home'), 'Start at the center', 'Your homepage is the anchor. Explore the sections and paths connected to it.');
  add(rank(node => node.outlinksBody + node.inlinksBody, pages.filter(node => node.kind === 'hub')),
    'Meet a section', 'A captured section brings a different part of this site into view.');
  const connected = rank(node => node.inlinksBody);
  if (connected && connected.inlinksBody > 0) add(connected, 'A connected corner', `${connected.inlinksBody} captured body ${connected.inlinksBody === 1 ? 'link points' : 'links point'} to this page.`);
  const deep = rank(node => node.clickDepth ?? -1);
  if (deep && (deep.clickDepth ?? -1) >= 2) add(deep, 'Take the scenic route', `This page was reached ${deep.clickDepth} internal link hops from home in the captured graph.`);
  add(rank(node => node.health === 'broken' ? 4 : node.health === 'unavailable' ? 3 : node.health === 'orphan' ? 2 : 1, pages.filter(hasNodeIssue)),
    'Something to inspect', 'The saved capture records a flag here. Open the inspector to see the observation and its context.');
  const gateway = rank(node => node.externalDomainsOut);
  if (gateway && gateway.externalDomainsOut > 0) add(gateway, 'A window to the wider web', `This page links to ${gateway.externalDomainsOut} external ${gateway.externalDomainsOut === 1 ? 'domain' : 'domains'} in the capture.`);
  const read = rank(node => node.pageChecks?.wordsMeasured === false ? 0 : node.wordCount);
  if (read && read.wordCount > 0) add(read, 'Read beyond the map', `${read.wordCount.toLocaleString()} words were retained for this page. Its Markdown note is ready to explore.`);
  for (const node of [...nodes].sort((a, b) => a.path.localeCompare(b.path))) {
    if (stops.length >= 4) break;
    add(node, 'Another perspective', 'A different place in this saved map. Follow a captured link to see where it leads.');
  }
  return stops;
}

export function chooseDiscoveryNode(nodes: readonly SiteNode[], visited: ReadonlySet<string>, currentId: string | null, random = Math.random()): SiteNode | null {
  const others = nodes.filter(node => node.id !== currentId);
  const fresh = others.filter(node => !visited.has(node.id));
  const pool = fresh.length ? fresh : others;
  if (!pool.length) return null;
  const value = Number.isFinite(random) ? Math.max(0, Math.min(.999999, random)) : 0;
  return pool[Math.floor(value * pool.length)] ?? null;
}

export function discoveryConnections(manifest: SiteGraphManifest, nodeId: string | null, visible: ReadonlySet<string>, showChromeLinks: boolean): DiscoveryConnection[] {
  if (!nodeId) return [];
  const nodeById = new Map(manifest.nodes.map(node => [node.id, node]));
  const peers = new Map<string, { node: SiteNode; incoming: boolean; outgoing: boolean; anchor: string }>();
  for (const edge of manifest.edges) {
    if (edge.kind === 'sitemap-hierarchy' || (edge.kind === 'internal-chrome' && !showChromeLinks)) continue;
    const outgoing: boolean = edge.source === nodeId;
    if (!outgoing && edge.target !== nodeId) continue;
    const peerId: string = outgoing ? edge.target : edge.source;
    const node = nodeById.get(peerId);
    if (!node || peerId === nodeId || !visible.has(peerId)) continue;
    const peer = peers.get(peerId) ?? { node, incoming: false, outgoing: false, anchor: edge.anchor ?? '' };
    peer.outgoing ||= outgoing;
    peer.incoming ||= !outgoing;
    if (outgoing && edge.anchor) peer.anchor = edge.anchor;
    peers.set(peerId, peer);
  }
  return [...peers.values()].sort((a, b) => Number(b.outgoing) - Number(a.outgoing) || a.node.title.localeCompare(b.node.title))
    .map(peer => ({ node: peer.node, direction: peer.incoming && peer.outgoing ? 'both' : peer.outgoing ? 'outgoing' : 'incoming', anchor: peer.anchor }));
}
