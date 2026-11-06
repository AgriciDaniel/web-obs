import { friendlyEngineError, friendlySpawnError } from './crawlErrors';
import { applyPipelineProgress } from '../data/crawlProgress';
import { type ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { clearTimeout as clearNodeTimeout, setTimeout as setNodeTimeout } from 'node:timers';
import {
  FileSystemAdapter,
  ItemView,
  Notice,
  TFile,
  type ViewStateResult,
  type WorkspaceLeaf,
  normalizePath,
} from 'obsidian';
import App from '../App';
import { type ResyncAdapter, resyncVaultFolder } from './vaultResync';
import {
  type MountedSiteGlobeView,
  WEB_OBS_VIEW_TYPE,
  mountSiteGlobeApp,
  sanitizeExternalHttpUrl,
  sanitizeVaultRelativePath,
} from '../obsidian/hostAdapter';
import type {
  CrawlOptions,
  CrawlProgressState,
  GlobePluginCommand,
  GlobeViewMode,
  HostEventHandlers,
  SiteGraphManifest,
  SiteHostAdapter,
  SiteSummaryItem,
  ThemeMode,
} from '../types/site';
import type { WebObsPluginSettings } from './settings';
import { ensurePythonEngineReady } from './pythonRuntime';
import { WindowVisibilityBinding } from './windowVisibility';
import { JsonlDecoder } from '../data/jsonl';
import { isSafeSiteId, parseSiteManifest } from '../data/validateManifest';

/** A logo larger than this is not drawn on the map; real logos are far smaller. */
const MAX_MAP_ASSET_BYTES = 4 * 1024 * 1024;
const MAP_ASSET_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'ico', 'avif']);

export interface WebObsPluginBridge {
  manifest: { dir?: string };
  settings: WebObsPluginSettings;
}

export class SiteGlobeView extends ItemView {
  navigation = false;
  private plugin: WebObsPluginBridge;
  private mounted: MountedSiteGlobeView | null = null;
  private visibility: WindowVisibilityBinding | null = null;
  private listeners = new Set<HostEventHandlers>();
  private pendingViewMode?: GlobeViewMode;
  private currentPaused = false;
  private activeChild: ChildProcessWithoutNullStreams | null = null;
  private crawlGeneration = 0;
  private activeCrawlController: AbortController | null = null;
  private activeCrawlProgress: CrawlProgressState | null = null;
  private readonly stoppingChildren = new WeakSet<ChildProcessWithoutNullStreams>();
  private closed = false;
  private latestManifestCache: SiteGraphManifest | null = null;

  constructor(leaf: WorkspaceLeaf, plugin: WebObsPluginBridge) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType(): string {
    return WEB_OBS_VIEW_TYPE;
  }

  getDisplayText(): string {
    return 'Web-Obs Site Globe';
  }

  getIcon(): string {
    return 'globe';
  }

  override async setState(
    state: Record<string, unknown>,
    result: ViewStateResult
  ): Promise<void> {
    const raw = state?.viewMode;
    if (raw === 'globe' || raw === 'road' || raw === 'clusters') {
      this.pendingViewMode = raw;
      this.dispatchCommand({ type: 'set-view-mode', viewMode: raw });
    }
    await super.setState(state, result);
  }

  override getState(): Record<string, unknown> {
    return {
      ...super.getState(),
      viewMode: this.pendingViewMode ?? this.plugin.settings.defaultViewMode,
    };
  }

  async onOpen(): Promise<void> {
    this.closed = false;
    this.contentEl.empty();
    this.contentEl.addClass('web-obs-view-content');

    this.registerEvent(
      this.app.workspace.on('css-change', () => {
        this.emitTheme();
      })
    );

    this.registerEvent(
      this.app.workspace.on('file-open', (file) => {
        if (this.plugin.settings.syncActiveNote && file) {
          this.focusNoteInGlobe(file, true);
        }
      })
    );

    this.tryInit();
  }

  override onResize(): void {
    if (!this.mounted) {
      this.tryInit();
    }
  }

  private getVaultBasePath(): string | null {
    const adapter = this.app.vault.adapter;
    if (adapter instanceof FileSystemAdapter) {
      return adapter.getBasePath();
    }
    return null;
  }

  private resolveEngineScriptPath(vaultBase: string): string | null {
    const pluginRel = this.plugin.manifest.dir ?? '.obsidian/plugins/web-obs';
    const bundled = path.join(vaultBase, pluginRel, 'engine', 'crawl_site.py');
    if (fs.existsSync(bundled)) return bundled;
    const workspaceDirect = path.join(vaultBase, 'engine', 'crawl_site.py');
    if (fs.existsSync(workspaceDirect)) return workspaceDirect;
    return null;
  }

  private async listVaultSites(): Promise<SiteSummaryItem[]> {
    const vaultBase = this.getVaultBasePath();
    if (!vaultBase) return [];
    const sitesDir = path.join(vaultBase, 'sites');
    if (!fs.existsSync(sitesDir)) return [];

    const items: SiteSummaryItem[] = [];
    for (const entry of fs.readdirSync(sitesDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const mp = path.join(sitesDir, entry.name, '_site-graph.json');
      if (!fs.existsSync(mp)) continue;
      try {
        const parsed = parseSiteManifest(JSON.parse(fs.readFileSync(mp, 'utf8')));
        items.push({
          siteId: parsed.siteId || entry.name,
          domain: parsed.domain || entry.name,
          capturedAt: parsed.capturedAt || '',
          pagesCrawled: parsed.stats?.pagesCrawled ?? 0,
          externalDomains: parsed.stats?.externalDomains ?? 0,
        });
      } catch {
        // Ignore unreadable manifest
      }
    }
    items.sort((a, b) => b.capturedAt.localeCompare(a.capturedAt));
    return items;
  }

  private async loadVaultSiteManifest(siteId: string): Promise<SiteGraphManifest | null> {
    const vaultBase = this.getVaultBasePath();
    if (!vaultBase) return null;
    if (!isSafeSiteId(siteId)) return null;
    const mp = path.join(vaultBase, 'sites', siteId, '_site-graph.json');
    if (!fs.existsSync(mp)) return null;
    try {
      const parsed = parseSiteManifest(JSON.parse(fs.readFileSync(mp, 'utf8')));
      if (parsed.siteId !== siteId) return null;
      this.latestManifestCache = parsed;
      return parsed;
    } catch {
      return null;
    }
  }

  private emitCrawlProgress(prog: CrawlProgressState): void {
    for (const l of this.listeners) {
      l.onCrawlProgress?.(prog);
    }
  }

  private stopNativeChild(child: ChildProcessWithoutNullStreams): void {
    if (this.stoppingChildren.has(child) || child.exitCode !== null || child.signalCode !== null) return;
    this.stoppingChildren.add(child);
    // SIGTERM allows backend cleanup; escalate only for this still-running owned child.
    const timer = setNodeTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        try { child.kill('SIGKILL'); } catch { /* The child may already have exited. */ }
      }
    }, 2500);
    timer.unref();
    child.once('close', () => clearNodeTimeout(timer));
    try { child.kill('SIGTERM'); } catch { /* The child may have failed to spawn. */ }
  }

  private cancelActiveCrawl(notify: boolean): void {
    const progress = this.activeCrawlProgress;
    const child = this.activeChild;
    this.crawlGeneration += 1;
    this.activeChild = null;
    this.activeCrawlController?.abort();
    this.activeCrawlController = null;
    this.activeCrawlProgress = null;
    if (child) this.stopNativeChild(child);
    if (notify && !this.closed && progress) {
      this.emitCrawlProgress({ ...progress, running: false, phase: 'cancelled', message: 'Capture cancelled.', error: null });
    }
  }

  public async runCrawlFromPlugin(options: CrawlOptions): Promise<SiteGraphManifest | null> {
    if (this.closed) return null;
    const vaultBase = this.getVaultBasePath();
    if (!vaultBase) {
      new Notice('Web-Obs requires a local desktop vault.');
      return null;
    }
    const scriptPath = this.resolveEngineScriptPath(vaultBase);
    if (!scriptPath) {
      new Notice('Web-Obs engine/crawl_site.py not found in plugin folder.');
      return null;
    }
    const continuing = options.continueLinksSiteId;
    if (continuing !== undefined && !isSafeSiteId(continuing)) throw new Error('Invalid saved site ID.');
    const target = options.url.trim();
    if (!target) {
      new Notice('Enter a website domain or URL.');
      return null;
    }

    this.cancelActiveCrawl(false);
    const generation = this.crawlGeneration;
    const controller = new AbortController();
    this.activeCrawlController = controller;
    const isCurrent = () => !this.closed && !controller.signal.aborted &&
      generation === this.crawlGeneration && this.activeCrawlController === controller;
    const releasePreparation = () => {
      if (this.activeCrawlController === controller) {
        this.activeCrawlController = null;
        this.activeCrawlProgress = null;
      }
    };
    const requestedMax = options.maxPages ?? this.plugin.settings.defaultMaxPages;
    const maxPages = Number.isFinite(requestedMax) ? Math.max(1, Math.min(1000, Math.trunc(requestedMax))) : 250;
    const downloadImages = options.downloadImages ?? this.plugin.settings.downloadImages;
    const requestedRender = continuing ? 'never' : options.renderMode ?? this.plugin.settings.renderMode;
    const renderMode = requestedRender === 'never' || requestedRender === 'always' ? requestedRender : 'auto';
    const configuredPy = this.plugin.settings.pythonBinary || 'python3.14';
    const state: CrawlProgressState = {
      operation: options.continueLinksSiteId ? 'links' : 'capture', running: true, targetUrl: target, phase: continuing ? 'crawl' : 'sitemap', message: 'Checking local engine capabilities...',
      sitemapsFound: 0, sitemapUrlsCount: 0, currentPage: 0, maxPages, currentUrl: target, error: null,
    };
    this.activeCrawlProgress = state;
    this.emitCrawlProgress({ ...state });

    let ready: { pythonBin: string; error?: string };
    try {
      ready = await ensurePythonEngineReady(vaultBase, scriptPath, configuredPy, (message) => {
        if (!isCurrent()) return;
        state.message = message;
        this.emitCrawlProgress({ ...state });
      }, { renderMode, signal: controller.signal });
    } catch (error) {
      if (isCurrent()) {
        const message = error instanceof Error ? error.message : 'Engine capability check failed.';
        this.emitCrawlProgress({ ...state, running: false, phase: 'error', message, error: message });
        new Notice(message);
      }
      releasePreparation();
      return null;
    }
    // Closing, cancelling, or starting another request invalidates awaited preparation.
    if (!isCurrent()) return null;
    if (ready.error) {
      this.emitCrawlProgress({ ...state, running: false, phase: 'error', message: ready.error, error: ready.error });
      new Notice(ready.error);
      releasePreparation();
      return null;
    }
    state.message = continuing ? 'Loading saved link targets...' : 'Discovering sitemaps...';
    this.emitCrawlProgress({ ...state });
    if (!isCurrent()) return null;
    const args = continuing
      ? [scriptPath, continuing, '--vault', vaultBase, '--continue-links']
      : [scriptPath, target, '--vault', vaultBase, '--max-pages', String(maxPages), '--render', renderMode, '--image-mode', (options.imageMode ?? this.plugin.settings.imageMode) === 'all' ? 'all' : 'preferred'];
    if (!downloadImages) args.push('--no-images');
    if (!continuing) {
      if (!(options.browserAudit ?? this.plugin.settings.browserAudit ?? true)) args.push('--no-browser-audit');
      if (options.spellCheck ?? this.plugin.settings.spellCheck ?? false) args.push('--spell-check');
      if (!(options.dnsChecks ?? this.plugin.settings.dnsChecks ?? true)) args.push('--no-dns-checks');
      if (!(options.pageSnapshots ?? this.plugin.settings.pageSnapshots ?? true)) args.push('--no-snapshots');
      else args.push('--snapshot-limit', String(Math.max(1, Math.min(500, Math.trunc(options.snapshotLimit ?? this.plugin.settings.snapshotLimit ?? 25)))));
      if (options.snapshotHtml ?? this.plugin.settings.snapshotHtml ?? false) args.push('--snapshot-html');
      if (!(options.tlsCheck ?? this.plugin.settings.tlsCheck ?? true)) args.push('--no-tls-check');
      if (!(options.taskList ?? this.plugin.settings.taskList ?? true)) args.push('--no-tasks');
      const deadlineSec = options.deadlineSec ?? (this.plugin.settings.captureDeadlineMinutes ?? 0) * 60;
      if (Number.isFinite(deadlineSec) && deadlineSec > 0) args.push('--deadline', String(Math.max(1, Math.min(86400, Math.round(deadlineSec)))));
    }

    return new Promise((resolve) => {
      let child: ChildProcessWithoutNullStreams;
      let settled = false;
      let stderrText = '';
      let completedSiteId = '';
      let partialCapture = false;
      let terminalError = '';
      const finish = (manifest: SiteGraphManifest | null, error = '') => {
        if (settled) return;
        settled = true;
        controller.signal.removeEventListener('abort', onAbort);
        if (error && isCurrent()) {
          this.emitCrawlProgress({ ...state, running: false, phase: 'error', message: error, error });
        }
        if (this.activeChild === child) this.activeChild = null;
        releasePreparation();
        resolve(manifest);
      };
      const onAbort = () => {
        if (child) this.stopNativeChild(child);
        finish(null);
      };
      const count = (value: unknown, fallback: number) =>
        typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback;
      const decoder = new JsonlDecoder((event) => {
        if (!isCurrent() || settled) return;
        if (completedSiteId) throw new Error('Crawler returned events after completion.');
        if (applyPipelineProgress(state, event)) {
          // Independent lanes are already applied.
        } else if (event.event === 'phase') {
          state.currentUrl = '';
          if (event.phase === 'sitemap' || event.phase === 'crawl' || event.phase === 'compile') state.phase = event.phase;
          if (typeof event.message === 'string') state.message = event.message;
        } else if (event.event === 'sitemap_progress') {
          state.sitemapsFound = count(event.sitemapsFound, state.sitemapsFound);
          state.sitemapUrlsCount = count(event.urlsDiscovered, state.sitemapUrlsCount);
          if (typeof event.sitemapUrl === 'string') state.currentUrl = event.sitemapUrl;
        } else if (event.event === 'sitemap_done') {
          state.sitemapsFound = count(event.sitemapsCount, state.sitemapsFound);
          state.sitemapUrlsCount = count(event.sitemapUrlsCount, state.sitemapUrlsCount);
        } else if (event.event === 'crawl_progress') {
          state.phase = 'crawl';
          state.currentPage = count(event.current, state.currentPage);
          state.maxPages = count(event.maxPages, state.maxPages);
          if (typeof event.url === 'string') state.currentUrl = event.url;
          state.message = `Crawling page ${state.currentPage} of ${state.maxPages}`;
        } else if (event.event === 'complete') {
          if (!isSafeSiteId(event.siteId)) throw new Error('Crawler returned an invalid capture ID.');
          completedSiteId = event.siteId;
          partialCapture = event.captureStatus === 'partial';
          state.phase = 'compile';
          state.message = 'Checking saved capture...';
        } else if (event.event === 'error') {
          terminalError = typeof event.message === 'string' ? event.message : 'Crawler reported an error.';
          state.error = terminalError;
          state.message = terminalError;
        }
        this.emitCrawlProgress({ ...state });
      });
      try {
        child = spawn(ready.pythonBin, args, { cwd: vaultBase, windowsHide: true });
      } catch (error) {
        finish(null, error instanceof Error ? error.message : 'Could not start the crawler.');
        return;
      }
      this.activeChild = child;
      controller.signal.addEventListener('abort', onAbort, { once: true });
      if (!isCurrent()) { onAbort(); return; }

      child.stdout.on('data', (chunk: Buffer) => {
        if (!isCurrent() || settled || terminalError) return;
        try { decoder.push(chunk); } catch (error) {
          terminalError = error instanceof Error ? error.message : 'Invalid crawler stream.';
          this.stopNativeChild(child);
        }
      });
      child.stderr.on('data', (chunk: Buffer) => {
        if (isCurrent() && !settled) stderrText = (stderrText + chunk.toString('utf8')).slice(-8192);
      });
      child.on('error', (error) => finish(null, friendlySpawnError(ready.pythonBin, error.message)));
      child.on('close', async (code, signal) => {
        if (settled) return;
        if (!isCurrent()) { finish(null); return; }
        if (this.activeChild === child) this.activeChild = null;
        try {
          if (!terminalError) decoder.finish();
          if (terminalError) { finish(null, terminalError); return; }
          if (code !== 0) {
            finish(null, friendlyEngineError(stderrText, `Crawler exited with ${signal ? `signal ${signal}` : `code ${code}`}.`));
            return;
          }
          if (!completedSiteId) { finish(null, 'Crawler exited without a completion record.'); return; }
          const manifest = await this.loadVaultSiteManifest(completedSiteId);
          if (!isCurrent()) { finish(null); return; }
          if (!manifest) { finish(null, 'Crawler reported completion, but its saved capture could not be validated.'); return; }
          await this.resyncSiteFolder(completedSiteId);
          if (!isCurrent()) { finish(null); return; }
          const sites = await this.listVaultSites();
          if (!isCurrent()) { finish(null); return; }
          state.running = false;
          state.phase = 'done';
          state.message = continuing ? 'Saved link checks updated.' : partialCapture ? 'Partial capture saved; some collection gaps remain.' : 'Capture complete.';
          state.error = null;
          this.emitCrawlProgress({ ...state });
          for (const listener of this.listeners) {
            if (!isCurrent()) break;
            listener.onSitesChanged?.(sites, manifest);
          }
          if (!isCurrent()) { finish(null); return; }
          new Notice(`${partialCapture ? 'Partial capture' : 'Captured'} ${manifest.domain} (${manifest.stats.pagesCrawled} pages).`);
          finish(manifest);
        } catch (error) {
          finish(null, error instanceof Error ? error.message : 'Could not load the saved capture.');
        }
      });
    });
  }

  /** The capture swaps the site folder in one rename; make Obsidian index what is there now. */
  private async resyncSiteFolder(siteId: string): Promise<void> {
    const adapter = this.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) return;
    try {
      const result = await resyncVaultFolder(adapter as unknown as ResyncAdapter, normalizePath(`sites/${siteId}`));
      if (result.state === 'unsupported') new Notice('Capture saved. If new snapshots or notes do not show yet, reload Obsidian once.');
    } catch {
      new Notice('Capture saved. If new snapshots or notes do not show yet, reload Obsidian once.');
    }
  }

  private tryInit(): void {
    if (this.closed || this.mounted) return;
    const { clientWidth: w, clientHeight: h } = this.contentEl;
    if (w < 10 || h < 10) return;

    this.visibility = new WindowVisibilityBinding(this.contentEl, (paused) => {
      this.currentPaused = paused;
      for (const l of this.listeners) {
        l.onPauseChange?.(paused);
      }
    });
    const doc = this.contentEl.ownerDocument;
    this.visibility.bind(doc.defaultView ?? window, doc);

    const host: SiteHostAdapter = {
      mode: 'obsidian',
      vaultName: this.app.vault.getName(),
      initialTheme: this.resolveCurrentTheme(),
      initialViewMode: this.pendingViewMode ?? this.plugin.settings.defaultViewMode,
      listSites: () => this.listVaultSites(),
      loadSiteManifest: (siteId) => this.loadVaultSiteManifest(siteId),
      startCrawl: (opts) => this.runCrawlFromPlugin(opts),
      cancelCrawl: () => this.cancelActiveCrawl(true),
      onOpenNote: (vaultRelativePath: string, splitPane?: boolean) => {
        void this.openVaultNote(vaultRelativePath, splitPane);
      },
      resolveAssetUrl: (vaultRelativePath: string) => {
        const safe = sanitizeVaultRelativePath(vaultRelativePath);
        if (!safe) return null;
        const file = this.app.vault.getAbstractFileByPath(normalizePath(safe));
        return file instanceof TFile ? this.app.vault.getResourcePath(file) : null;
      },
      readAssetBytes: async (vaultRelativePath: string) => {
        const safe = sanitizeVaultRelativePath(vaultRelativePath);
        if (!safe || !safe.startsWith('sites/')) return null;
        const file = this.app.vault.getAbstractFileByPath(normalizePath(safe));
        // Images only, so this can never become a way to read notes or capture data.
        if (!(file instanceof TFile) || !MAP_ASSET_EXTENSIONS.has(file.extension.toLowerCase()) || file.stat.size > MAX_MAP_ASSET_BYTES) return null;
        try {
          return await this.app.vault.readBinary(file);
        } catch {
          return null;
        }
      },
      onOpenExternalUrl: (url: string) => {
        const safe = sanitizeExternalHttpUrl(url);
        if (safe) window.open(safe, '_blank', 'noopener,noreferrer');
      },
      subscribeHostEvents: (handlers: HostEventHandlers) => {
        this.listeners.add(handlers);
        handlers.onPauseChange?.(this.currentPaused);
        return () => {
          this.listeners.delete(handlers);
        };
      },
      onWebGLContextLost: () => {
        this.rebuild();
      },
    };

    this.mounted = mountSiteGlobeApp(this.contentEl, host, App);
  }

  private rebuild(): void {
    this.mounted?.unmount();
    this.mounted = null;
    this.visibility?.dispose();
    this.visibility = null;
    this.contentEl.empty();
    this.tryInit();
  }

  public resolveCurrentTheme(): ThemeMode {
    const pref = this.plugin.settings.themeBehavior;
    if (pref === 'dark' || pref === 'light') return pref;
    return document.body.classList.contains('theme-dark') ? 'dark' : 'light';
  }

  public emitTheme(): void {
    const next = this.resolveCurrentTheme();
    for (const l of this.listeners) {
      l.onThemeChange?.(next);
    }
  }

  public dispatchCommand(cmd: GlobePluginCommand): void {
    if (cmd.type === 'set-view-mode') {
      this.pendingViewMode = cmd.viewMode;
    }
    for (const l of this.listeners) {
      l.onCommand?.(cmd);
    }
  }

  public focusNoteInGlobe(file: TFile, fly = true): boolean {
    const safePath = sanitizeVaultRelativePath(file.path);
    if (!safePath || !this.latestManifestCache) return false;
    const match = this.latestManifestCache.nodes.find(
      (n) => n.obsidianPath.toLowerCase() === safePath.toLowerCase()
    );
    if (match) {
      this.dispatchCommand({ type: 'select-node', nodeId: match.id, fly });
      return true;
    }
    return false;
  }

  private async openVaultNote(
    vaultRelativePath: string,
    splitOverride?: boolean
  ): Promise<void> {
    const safe = sanitizeVaultRelativePath(vaultRelativePath);
    if (!safe) {
      new Notice('Invalid vault path.');
      return;
    }
    const norm = normalizePath(safe);
    const abstractFile = this.app.vault.getAbstractFileByPath(norm);
    if (!(abstractFile instanceof TFile)) {
      new Notice(`Note not found in vault: ${norm}`);
      return;
    }
    // Obsidian has no view for files such as CSV. Hand them to the system's default app.
    if (!['md', 'canvas', 'base', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'avif', 'pdf'].includes(abstractFile.extension.toLowerCase())) {
      const app = this.app as unknown as { openWithDefaultApp?: (path: string) => unknown };
      if (typeof app.openWithDefaultApp === 'function') {
        void app.openWithDefaultApp(norm);
      } else {
        new Notice(`Open ${norm} from your file manager.`);
      }
      return;
    }

    const useSplit = splitOverride ?? this.plugin.settings.openInSplitPane;
    if (useSplit) {
      let neighborLeaf: WorkspaceLeaf | null = null;
      const myParent = this.leaf.parent;
      this.app.workspace.iterateAllLeaves((candidate) => {
        if (
          !neighborLeaf &&
          candidate !== this.leaf &&
          candidate.parent !== myParent &&
          candidate.view.getViewType() === 'markdown'
        ) {
          neighborLeaf = candidate;
        }
      });
      const targetLeaf = neighborLeaf ?? this.app.workspace.getLeaf('split');
      await targetLeaf.openFile(abstractFile);
      this.app.workspace.setActiveLeaf(targetLeaf, { focus: true });
    } else {
      const targetLeaf = this.app.workspace.getLeaf('tab');
      await targetLeaf.openFile(abstractFile);
    }
  }

  async onClose(): Promise<void> {
    this.closed = true;
    this.cancelActiveCrawl(false);
    this.mounted?.unmount();
    this.mounted = null;
    this.visibility?.dispose();
    this.visibility = null;
    this.listeners.clear();
    this.contentEl.empty();
  }
}
