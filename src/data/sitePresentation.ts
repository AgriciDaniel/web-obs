import type { NodeFilter, SiteNode } from '../types/site';

export function hasNodeIssue(node: SiteNode): boolean {
  return node.kind !== 'external-domain' && (
    ['orphan', 'unlisted', 'broken', 'redirect', 'unavailable'].includes(node.health) ||
    !node.metaDescription || node.h1.length === 0 || (node.seoIssues?.length ?? 0) > 0
  );
}

export function matchesNodeFilter(node: SiteNode, filter: NodeFilter): boolean {
  if (filter === 'hubs') return node.kind === 'home' || node.kind === 'hub';
  if (filter === 'pages') return node.kind !== 'external-domain';
  if (filter === 'orphans') return node.health === 'orphan' || node.health === 'unlisted';
  if (filter === 'issues') return hasNodeIssue(node);
  if (filter === 'external') return node.kind === 'external-domain';
  return true;
}

export function captureDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
