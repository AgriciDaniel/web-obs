import type { SiteNode } from '../types/site';

/** The text a node's label pill shows. The Road layout measures the same text to size its columns. */
export function shortPillLabel(node: SiteNode, domain?: string): string {
  if (node.kind === 'home') {
    const cleanDomain = (
      domain ||
      node.url.replace(/^https?:\/\//i, '').replace(/\/.*$/, '') ||
      'site'
    ).trim();
    return cleanDomain;
  }
  if (node.kind === 'external-domain') return node.title;
  const cleanTitle = node.title.split('|')[0].split(' - ')[0].trim();
  if (cleanTitle.length > 0 && cleanTitle.length <= 28) return cleanTitle;
  const p = node.path || '/';
  if (p.length <= 28) return p;
  const parts = p.split('/').filter(Boolean);
  const last = parts[parts.length - 1] ?? p;
  return `/${last.slice(0, 24)}`;
}
