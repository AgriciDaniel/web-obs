import { applyPipelineProgress } from '../data/crawlProgress';
import { createElement, type ComponentType } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { JsonlDecoder } from '../data/jsonl';
import { parseSiteManifest } from '../data/validateManifest';
import type {
  CrawlOptions,
  CrawlProgressState,
  HostEventHandlers,
  SiteGraphManifest,
  SiteHostAdapter,
  SiteSummaryItem,
  ThemeMode,
} from '../types/site';

export const WEB_OBS_VIEW_TYPE = 'web-obs-site-globe';
export const DEFAULT_VAULT_NAME = 'web-obs';

const eventText = (value: unknown, fallback = ''): string => typeof value === 'string' ? value : fallback;

const UNSAFE_SCHEME_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;
// eslint-disable-next-line no-control-regex -- Strip control bytes from URI display text.
const CTRL_CHAR_RE = /[\x00-\x1f\x7f-\x9f]/g;

export function sanitizeVaultRelativePath(rawPath: unknown): string | null {
  if (typeof rawPath !== 'string') return null;
  if (rawPath.length === 0 || rawPath.length > 300) return null;
  // eslint-disable-next-line no-control-regex -- Reject control bytes before path or URL normalization.
  if (/[\x00-\x1f\x7f]/.test(rawPath)) return null;

  const candidate = rawPath.replace(/\\/g, '/').trim();
  if (!candidate) return null;

  let decoded = candidate;
  try {
    decoded = decodeURIComponent(candidate).replace(/\\/g, '/').trim();
  } catch {
    return null;
  }

  for (const check of [candidate, decoded]) {
    // eslint-disable-next-line no-control-regex -- Reject control bytes before path or URL normalization.
    if (!check || /[\x00-\x1f\x7f]/.test(check)) return null;
    if (check.startsWith('/') || check.startsWith('~')) return null;
    if (UNSAFE_SCHEME_RE.test(check)) return null;
    const segments = check.split('/');
    for (const seg of segments) {
      const s = seg.trim();
      if (!s || s === '.' || s === '..' || s.startsWith('.')) {
        return null;
      }
    }
  }
  return candidate;
}

export function sanitizeExternalHttpUrl(rawUrl: unknown): string | null {
  if (typeof rawUrl !== 'string' || rawUrl.length === 0 || rawUrl.length > 1024) {
    return null;
  }
  // eslint-disable-next-line no-control-regex -- Reject control bytes before path or URL normalization.
  if (/[\x00-\x1f\x7f]/.test(rawUrl)) return null;
  let candidate = rawUrl.trim();
  if (!/^https?:\/\//i.test(candidate)) {
    candidate = `https://${candidate}`;
  }
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

export function buildObsidianUri(vaultName: string, obsidianPath: string): string {
  const safeVault =
    (typeof vaultName === 'string'
      ? vaultName.replace(CTRL_CHAR_RE, '').trim().slice(0, 80)
      : '') || DEFAULT_VAULT_NAME;
  const validatedPath = sanitizeVaultRelativePath(obsidianPath);
  const cleanPath = (validatedPath ?? 'README').replace(/\.md$/i, '');
  return `obsidian://open?vault=${encodeURIComponent(safeVault)}&file=${encodeURIComponent(cleanPath)}`;
}

/**
 * Standalone browser host adapter (powers `npm run dev` with live local API fallback).
 */
export function createStandaloneHost(vaultName = DEFAULT_VAULT_NAME): SiteHostAdapter {
  const listeners = new Set<HostEventHandlers>();
  let activeRun: { controller: AbortController; state: CrawlProgressState } | null = null;

  const emitProgress = (p: CrawlProgressState) => {
    for (const l of listeners) l.onCrawlProgress?.(p);
  };

  return {
    mode: 'standalone',
    vaultName,
    listSites: async (): Promise<SiteSummaryItem[]> => {
      try {
        const res = await fetch('/__web_obs/sites');
        if (!res.ok) return [];
        const data = (await res.json()) as { sites?: SiteSummaryItem[] };
        return Array.isArray(data.sites) ? data.sites : [];
      } catch {
        return [];
      }
    },
    loadSiteManifest: async (siteId: string): Promise<SiteGraphManifest | null> => {
      try {
        const res = await fetch(`/__web_obs/site?id=${encodeURIComponent(siteId)}`);
        if (!res.ok) return null;
        return parseSiteManifest(await res.json());
      } catch {
        return null;
      }
    },
    readAssetBytes: async (vaultRelativePath: string): Promise<ArrayBuffer | null> => {
      const safe = sanitizeVaultRelativePath(vaultRelativePath);
      if (!safe || !safe.startsWith('sites/')) return null;
      try {
        const res = await fetch(`/__web_obs/asset?path=${encodeURIComponent(safe)}`);
        return res.ok ? await res.arrayBuffer() : null;
      } catch {
        return null;
      }
    },
    startCrawl: async (options: CrawlOptions): Promise<SiteGraphManifest | null> => {
      activeRun?.controller.abort();
      const controller = new AbortController();
      const state: CrawlProgressState = {
        operation: options.continueLinksSiteId ? 'links' : 'capture', running: true, targetUrl: options.url, phase: options.continueLinksSiteId ? 'crawl' : 'sitemap',
        message: options.continueLinksSiteId ? 'Loading saved link targets...' : 'Starting sitemap discovery...', sitemapsFound: 0,
        sitemapUrlsCount: 0, currentPage: 0, maxPages: options.maxPages ?? 250,
        currentUrl: options.url, error: null,
      };
      const run = { controller, state };
      activeRun = run;
      const publish = () => { if (activeRun === run) emitProgress({ ...state }); };
      publish();
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      try {
        const res = await fetch(options.continueLinksSiteId ? '/__web_obs/continue-links' : '/__web_obs/crawl', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(options), signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`Capture endpoint unavailable (HTTP ${res.status}).`);
        reader = res.body.getReader();
        let completedSiteId = '';
        let partial = false;
        const decoder = new JsonlDecoder((ev) => {
          if (activeRun !== run || controller.signal.aborted) return;
          if (completedSiteId) throw new Error('Crawler returned events after completion.');
          if (ev.event === 'error') throw new Error(eventText(ev.message, 'Crawl failed'));
          if (applyPipelineProgress(state, ev)) {
            // Independent lanes are already applied.
          } else if (ev.event === 'phase') {
            state.currentUrl = '';
            if (['sitemap', 'crawl', 'compile'].includes(eventText(ev.phase))) state.phase = ev.phase as CrawlProgressState['phase'];
            state.message = eventText(ev.message);
          } else if (ev.event === 'sitemap_progress') {
            state.sitemapsFound = Number(ev.sitemapsFound ?? state.sitemapsFound);
            state.sitemapUrlsCount = Number(ev.urlsDiscovered ?? state.sitemapUrlsCount);
            state.currentUrl = eventText(ev.sitemapUrl);
          } else if (ev.event === 'sitemap_done') {
            state.sitemapsFound = Number(ev.sitemapsCount ?? 0);
            state.sitemapUrlsCount = Number(ev.sitemapUrlsCount ?? 0);
          } else if (ev.event === 'crawl_progress') {
            state.phase = 'crawl';
            state.currentPage = Number(ev.current ?? state.currentPage);
            state.maxPages = Number(ev.maxPages ?? state.maxPages);
            state.currentUrl = eventText(ev.url);
            state.message = `Crawling page ${state.currentPage} of ${state.maxPages}`;
          } else if (ev.event === 'complete') {
            completedSiteId = eventText(ev.siteId);
            if (!completedSiteId) throw new Error('Crawler completed without a site ID.');
            partial = ev.captureStatus === 'partial';
            state.phase = 'compile';
            state.message = 'Loading the saved capture...';
          }
          publish();
        });
        while (true) {
          const chunk = await reader.read();
          if (activeRun !== run || controller.signal.aborted) return null;
          if (chunk.done) break;
          decoder.push(chunk.value);
        }
        decoder.finish();
        if (!completedSiteId) throw new Error('Capture stream ended before completion. Please retry.');
        const manifestRes = await fetch(`/__web_obs/site?id=${encodeURIComponent(completedSiteId)}`, { signal: controller.signal });
        if (!manifestRes.ok) throw new Error(`Saved capture could not be loaded (HTTP ${manifestRes.status}).`);
        const manifest = parseSiteManifest(await manifestRes.json());
        if (activeRun !== run || controller.signal.aborted) return null;
        state.running = false;
        state.phase = 'done';
        state.message = options.continueLinksSiteId ? 'Saved link checks updated' : partial ? 'Capture saved with collection gaps' : 'Capture complete';
        publish();
        return manifest;
      } catch (err) {
        if (activeRun !== run) return null;
        const cancelled = controller.signal.aborted;
        const message = cancelled ? 'Capture cancelled' : err instanceof Error ? err.message : 'Capture failed';
        state.running = false;
        state.phase = cancelled ? 'cancelled' : 'error';
        state.message = message;
        state.error = cancelled ? null : message;
        publish();
        return null;
      } finally {
        if (reader) {
          try { await reader.cancel(); } catch { /* The stream may already be closed. */ }
          reader.releaseLock();
        }
        if (activeRun === run) activeRun = null;
      }
    },
    cancelCrawl: () => {
      const run = activeRun;
      if (!run) return;
      run.controller.abort();
      emitProgress({ ...run.state, running: false, phase: 'cancelled', message: 'Capture cancelled', error: null });
      activeRun = null;
    },
    onOpenNote: (vaultRelativePath: string) => {
      if (!sanitizeVaultRelativePath(vaultRelativePath)) return;
      const uri = buildObsidianUri(vaultName, vaultRelativePath);
      window.open(uri, '_self');
    },
    onOpenExternalUrl: (url: string) => {
      const safe = sanitizeExternalHttpUrl(url);
      if (safe) window.open(safe, '_blank', 'noopener,noreferrer');
    },
    subscribeHostEvents: (handlers: HostEventHandlers) => {
      listeners.add(handlers);
      return () => {
        listeners.delete(handlers);
      };
    },
  };
}

export interface MountedSiteGlobeView {
  unmount: () => void;
}

export function mountSiteGlobeApp(
  containerEl: HTMLElement,
  host: SiteHostAdapter,
  AppComponent: ComponentType<{ host: SiteHostAdapter; initialTheme?: ThemeMode }>
): MountedSiteGlobeView {
  const root: Root = createRoot(containerEl);
  root.render(createElement(AppComponent, { host, initialTheme: host.initialTheme }));
  return {
    unmount: () => root.unmount(),
  };
}
