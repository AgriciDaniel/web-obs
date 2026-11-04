import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ChartNoAxesCombined,
  ArrowRight,
  CheckCircle2,
  FolderGit2,
  GitFork,
  Globe,
  Layers,
  Loader2,
  Moon,
  MoreHorizontal,
  PanelLeft,
  Orbit,
  Plus,
  RotateCcw,
  Route,
  Search,
  Sun,
  X,
} from 'lucide-react';
import { PREVIEW_SITE_MANIFEST } from './data/demoSite';
import { InspectorDrawer } from './components/InspectorDrawer';
import { SiteGlobeCanvas3D } from './components/SiteGlobeCanvas3D';
import { SiteIntelDrawer } from './components/SiteIntelDrawer';
import { SiteAuditPanel } from './components/SiteAuditPanel';
import { PageExplorer } from './components/PageExplorer';
import { SiteOverview } from './components/SiteOverview';
import { attentionNodeIds } from './data/mapAttention';
import { MenuButton } from './components/MapMenus';
import { ViewGizmo3D, type ViewGizmoHandle } from './components/ViewGizmo3D';
import { createStandaloneHost } from './obsidian/hostAdapter';
import type {
  CameraAxisSnap,
  CrawlProgressState,
  GlobeViewMode,
  NodeFilter,
  SiteGraphManifest,
  SiteHostAdapter,
  SiteNode,
  SiteSummaryItem,
  ThemeMode,
} from './types/site';

interface AppProps {
  host?: SiteHostAdapter;
  initialTheme?: ThemeMode;
}

const EXPLORER_KEY = 'web-obs:explorer-open';

/** Per-viewer convenience only. Storage can be missing or blocked, so every access is guarded. */
const readExplorerOpen = (): boolean => {
  try { return typeof window !== 'undefined' && window.localStorage?.getItem(EXPLORER_KEY) === '1'; } catch { return false; }
};
const writeExplorerOpen = (open: boolean) => {
  try { window.localStorage?.setItem(EXPLORER_KEY, open ? '1' : '0'); } catch { /* storage unavailable */ }
};

const IDLE_PROGRESS: CrawlProgressState = {
  running: false,
  targetUrl: '',
  phase: 'idle',
  message: '',
  sitemapsFound: 0,
  sitemapUrlsCount: 0,
  currentPage: 0,
  maxPages: 250,
  currentUrl: '',
  error: null,
};

export const App: React.FC<AppProps> = ({ host, initialTheme = 'dark' }) => {
  const activeHost = useMemo(() => host ?? createStandaloneHost(), [host]);
  const urlInputRef = useRef<HTMLInputElement | null>(null);
  const centerInputRef = useRef<HTMLInputElement | null>(null);
  const gizmoRef = useRef<ViewGizmoHandle | null>(null);
  const auditButtonRef = useRef<HTMLButtonElement | null>(null);
  const drawerReturnFocusRef = useRef<HTMLElement | null>(null);

  const [theme, setTheme] = useState<ThemeMode>(
    activeHost.initialTheme ?? initialTheme
  );
  const [viewMode, setViewMode] = useState<GlobeViewMode>(
    activeHost.initialViewMode ?? 'globe'
  );
  const [paused, setPaused] = useState<boolean>(false);

  const [sites, setSites] = useState<SiteSummaryItem[]>([]);
  const [manifest, setManifest] = useState<SiteGraphManifest | null>(null);
  const [initialLoaded, setInitialLoaded] = useState<boolean>(false);

  const [urlInput, setUrlInput] = useState<string>('');
  const [progress, setProgress] = useState<CrawlProgressState>(IDLE_PROGRESS);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [intelOpen, setIntelOpen] = useState<boolean>(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [filter, setFilter] = useState<NodeFilter>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchOpen, setSearchOpen] = useState<boolean>(false);
  const [showExternal, setShowExternal] = useState<boolean>(false);
  const [explorerOpen, setExplorerOpen] = useState(readExplorerOpen);
  const [captureOpen, setCaptureOpen] = useState(false);
  useEffect(() => { writeExplorerOpen(explorerOpen); }, [explorerOpen]);
  const [showAllLinks, setShowAllLinks] = useState(false);
  const [showChromeLinks, setShowChromeLinks] = useState<boolean>(false);
  const [showPulses, setShowPulses] = useState<boolean>(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? !window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : true
  );
  const [autoRotate, setAutoRotate] = useState<boolean>(false);
  const [resetSignal, setResetSignal] = useState<number>(0);
  const [flyRequest, setFlyRequest] = useState<{ nodeId: string; seq: number } | null>(
    null
  );
  const [axisSnapRequest, setAxisSnapRequest] = useState<{
    axis: CameraAxisSnap;
    seq: number;
  } | null>(null);
  const closePanels = useCallback(() => {
    setSelectedId(null);
    setIntelOpen(false);
    setAuditOpen(false);
    requestAnimationFrame(() => drawerReturnFocusRef.current?.focus({ preventScroll: true }));
  }, []);

  const refreshSitesList = useCallback(
    async (preferSiteId?: string) => {
      const list = await activeHost.listSites();
      setSites(list);
      const targetId = preferSiteId ?? list[0]?.siteId;
      if (targetId) {
        const loaded = await activeHost.loadSiteManifest(targetId);
        if (loaded) {
          setManifest(loaded);
          setSelectedId(null);
        }
      }
      setInitialLoaded(true);
    },
    [activeHost]
  );

  useEffect(() => {
    void refreshSitesList();
  }, [refreshSitesList]);

  useEffect(() => {
    if (!activeHost.subscribeHostEvents) return;
    return activeHost.subscribeHostEvents({
      onThemeChange: (nextTheme) => setTheme(nextTheme),
      onPauseChange: (nextPaused) => setPaused(nextPaused),
      onCrawlProgress: (nextProg) => setProgress(nextProg),
      onSitesChanged: (nextSites, latest) => {
        setSites(nextSites);
        if (latest) {
          setManifest(latest);
          setSelectedId(null);
        }
      },
      onCommand: (cmd) => {
        if (cmd.type === 'set-view-mode') {
          setViewMode(cmd.viewMode);
          setAuditOpen(false);
        } else if (cmd.type === 'focus-capture-input') {
          setCaptureOpen(true);
          requestAnimationFrame(() => {
            const el = centerInputRef.current ?? urlInputRef.current;
            el?.focus();
            el?.select();
          });
        } else if (cmd.type === 'select-node') {
          setAuditOpen(false);
          setIntelOpen(false);
          setSelectedId(cmd.nodeId);
          if (cmd.fly) {
            setFlyRequest((prev) => ({ nodeId: cmd.nodeId, seq: (prev?.seq ?? 0) + 1 }));
          }
        } else if (cmd.type === 'reload-sites') {
          void refreshSitesList(cmd.selectSiteId);
        }
      },
    });
  }, [activeHost, refreshSitesList]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (selectedId || intelOpen || auditOpen) closePanels();
        setSearchOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [closePanels, selectedId, intelOpen, auditOpen]);

  const handleCaptureSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = urlInput.trim();
    if (!trimmed || progress.running) return;

    setSelectedId(null);
    setIntelOpen(false);
    const result = await activeHost.startCrawl({ url: trimmed });
    if (result) {
      setManifest(result);
      setUrlInput('');
      setCaptureOpen(false);
      const updatedList = await activeHost.listSites();
      setSites(updatedList);
      setProgress(IDLE_PROGRESS);
    }
  };

  const handleContinueLinks = async (returnToAudit = false) => {
    if (!manifest || progress.running) return;
    setSelectedId(null);
    const result = await activeHost.startCrawl({ url: manifest.origin, continueLinksSiteId: manifest.siteId, renderMode: 'never' });
    if (result) {
      setManifest(result);
      setProgress(IDLE_PROGRESS);
      if (returnToAudit) {
        setAuditOpen(true);
        requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.wo-audit-close')?.focus());
      } else setIntelOpen(true);
    }
  };

  const handleSwitchSite = async (siteId: string) => {
    setAuditOpen(false);
    setIntelOpen(false);
    setSearchQuery('');
    setFilter('all');
    if (siteId === PREVIEW_SITE_MANIFEST.siteId) {
      setManifest(PREVIEW_SITE_MANIFEST);
      setSelectedId(null);
      return;
    }
    const loaded = await activeHost.loadSiteManifest(siteId);
    if (loaded) {
      setManifest(loaded);
      setSelectedId(null);
    }
  };

  const selectedNode: SiteNode | null = useMemo(() => {
    if (!manifest || !selectedId) return null;
    return manifest.nodes.find((n) => n.id === selectedId) ?? null;
  }, [manifest, selectedId]);

  const attention = useMemo(() => attentionNodeIds(manifest), [manifest]);
  const counts = useMemo(() => {
    if (!manifest) {
      return { all: 0, hubs: 0, pages: 0, orphans: 0, issues: 0, external: 0 };
    }
    let hubs = 0;
    let pages = 0;
    let orphans = 0;
    let issues = 0;
    let external = 0;
    for (const n of manifest.nodes) {
      if (n.kind === 'external-domain') {
        external++;
        continue;
      }
      pages++;
      if (n.kind === 'home' || n.kind === 'hub') hubs++;
      if (n.health === 'orphan' || n.health === 'unlisted') orphans++;
      if (attention.has(n.id)) issues++;
    }
    return {
      all: showExternal ? pages + external : pages,
      hubs,
      pages,
      orphans,
      issues,
      external,
    };
  }, [manifest, showExternal, attention]);
  const legend = useMemo(() => {
    if (!manifest) return [];
    const has = (test: (n: SiteNode) => boolean) => manifest.nodes.some(test);
    return ([
      ['home', 'Home', 'wo-dot-home', has((n) => n.kind === 'home')],
      ['hub', 'Section', 'wo-dot-hub', has((n) => n.kind === 'hub')],
      ['page', 'Page', 'wo-dot-page', has((n) => n.kind === 'page')],
      ['orphan', 'Orphan or unlisted', 'wo-dot-orphan', has((n) => n.health === 'orphan' || n.health === 'unlisted')],
      ['broken', 'Broken', 'wo-dot-broken', has((n) => n.health === 'broken')],
      ['external', 'External', 'wo-dot-ext', showExternal && counts.external > 0],
    ] as const).filter(([, , , shown]) => shown);
  }, [manifest, showExternal, counts.external]);
  const layersOn = Number(showAllLinks) + Number(showExternal) + Number(showChromeLinks) + Number(showPulses);

  const showOnboardingCard = initialLoaded && !manifest && !progress.running;
  const selectPage = (id: string) => {
    drawerReturnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = manifest?.nodes.find((item) => item.id === id);
    if (node?.kind === 'external-domain') setShowExternal(true);
    setIntelOpen(false);
    setSelectedId(id);
    setFlyRequest((prev) => ({ nodeId: id, seq: (prev?.seq ?? 0) + 1 }));
  };
  const openPageFilter = (next: NodeFilter) => {
    setFilter(next);
    setExplorerOpen(true);
    setSearchQuery('');
    if (next === 'external') setShowExternal(true);
  };
  const openAudit = (event?: React.MouseEvent<HTMLElement>) => {
    drawerReturnFocusRef.current = event?.currentTarget ?? auditButtonRef.current;
    setSelectedId(null); setIntelOpen(false); setAuditOpen(true);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.wo-audit-close')?.focus());
  };

  return (
    <div className={`wo-shell wo-theme-${theme} ${manifest ? 'wo-workspace' : ''} ${auditOpen ? 'wo-audit-open' : ''} ${explorerOpen ? 'wo-explorer-open' : ''} ${selectedNode || intelOpen ? 'wo-inspector-open' : ''}`}>
      {/* 3D WebGL Globe Stage */}
      <SiteGlobeCanvas3D
        manifest={manifest}
        viewMode={viewMode}
        theme={theme}
        selectedId={selectedId}
        hoveredId={hoveredId}
        filter={filter}
        searchQuery={searchQuery}
        showExternal={showExternal}
        showChromeLinks={showChromeLinks}
        showAllLinks={showAllLinks}
        showPulses={showPulses}
        autoRotate={autoRotate}
        paused={paused || auditOpen}
        inspectorOpen={Boolean(selectedNode) || intelOpen}
        resetSignal={resetSignal}
        flyRequest={flyRequest}
        axisSnapRequest={axisSnapRequest}
        gizmoRef={gizmoRef}
        onBeginDiscovery={() => { setSelectedId(null); setIntelOpen(false); }}
        onSelectNode={(nid) => {
          if (nid) drawerReturnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          if (nid) setIntelOpen(false);
          setSelectedId(nid);
        }}
        onHoverNode={setHoveredId}
        onOpenNoteNode={(node) => activeHost.onOpenNote(node.obsidianPath, true)}
        onWebGLContextLost={activeHost.onWebGLContextLost}
      />

      {/* Toolbar: site and capture on the left, layout in the middle, panels and view tools on the right. */}
      <header className="wo-topbar">
        <div className="wo-topbar-left">
          <span className="wo-brand-pill" title="web-obs">
            <Orbit size={15} className="wo-brand-icon" aria-hidden="true" />
            <span className="wo-brand-name">web-obs</span>
          </span>

          {manifest && <button type="button" className={`wo-icon-btn wo-explorer-toggle ${explorerOpen ? 'is-active' : ''}`} aria-label="Pages: show or hide explorer" title="Pages" aria-expanded={explorerOpen} aria-controls="wo-page-explorer" onClick={() => setExplorerOpen((value) => !value)}><PanelLeft size={15} /></button>}

          {sites.length > 0 && (
            <select
              className="wo-site-select"
              value={manifest?.siteId ?? ''}
              onChange={(e) => void handleSwitchSite(e.target.value)}
              aria-label="Captured websites"
            >
              {manifest?.siteId === PREVIEW_SITE_MANIFEST.siteId && (
                <option value={PREVIEW_SITE_MANIFEST.siteId}>
                  studio.example (preview)
                </option>
              )}
              {sites.map((s) => (
                <option key={s.siteId} value={s.siteId}>
                  {s.domain} ({s.pagesCrawled}p)
                </option>
              ))}
            </select>
          )}

          {manifest && !progress.running && !auditOpen && (captureOpen ? (
            <form className="wo-inline-capture" onSubmit={handleCaptureSubmit} onKeyDown={(event) => {
              if (event.key === 'Escape') { event.stopPropagation(); setCaptureOpen(false); }
            }}>
              <Globe size={13} className="wo-capture-icon" />
              <input
                ref={urlInputRef}
                type="text"
                autoFocus
                className="wo-capture-input"
                placeholder="websiteexample.com"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                aria-label="Website domain or URL to capture"
              />
              <button type="submit" className="wo-capture-submit" disabled={!urlInput.trim()}>
                <span>Capture</span>
                <ArrowRight size={13} />
              </button>
              <button type="button" className="wo-search-clear" aria-label="Close capture" onClick={() => setCaptureOpen(false)}><X size={13} /></button>
            </form>
          ) : (
            <button type="button" className="wo-icon-btn" aria-label="Capture a website" title="Capture a website" onClick={() => setCaptureOpen(true)}><Plus size={15} /></button>
          ))}

          {manifest && !progress.running && !auditOpen && !captureOpen && (
            <SiteOverview manifest={manifest} onPages={() => openPageFilter('pages')}
              onAttention={() => (counts.issues > 0 ? openPageFilter('issues') : openAudit())}
              onBrokenLinks={(event?: React.MouseEvent<HTMLElement>) => openAudit(event)}
              onDomains={() => openPageFilter('external')} />
          )}
        </div>

        {manifest && (
          <div className="wo-mode-seg" role="tablist" aria-label="Layout mode" onKeyDown={(event) => {
            const modes: GlobeViewMode[] = ['globe', 'road', 'clusters'];
            const index = modes.indexOf(viewMode);
            const next = event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : event.key === 'Home' ? 0 : event.key === 'End' ? 2 : -1;
            if (next >= 0) {
              event.preventDefault();
              setViewMode(modes[next]);
              setAuditOpen(false);
              event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus();
            }
          }}>
            {([
              ['globe', 'Globe', Globe], ['road', 'Road', Route], ['clusters', 'Clusters', GitFork],
            ] as const).map(([mode, label, Icon]) => (
              <button key={mode} type="button" role="tab" aria-selected={viewMode === mode} tabIndex={viewMode === mode ? 0 : -1}
                className={`wo-mode-btn ${viewMode === mode ? 'is-active' : ''}`}
                onClick={() => { setViewMode(mode); setAuditOpen(false); }}>
                <Icon size={13} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        )}

        {manifest && (
          <div className="wo-topbar-right">
            <button type="button" ref={auditButtonRef} className={`wo-intel-btn ${auditOpen ? 'is-active' : ''}`} aria-pressed={auditOpen} aria-label="Site audit"
              onClick={(event) => {
                drawerReturnFocusRef.current = event.currentTarget;
                setSelectedId(null); setIntelOpen(false); setAuditOpen((value) => !value);
                requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.wo-audit-close')?.focus());
              }} title="Site audit: findings, coverage and charts">
              <ChartNoAxesCombined size={13} /><span>Site audit</span>
            </button>

            {manifest.siteIntel && (
              <button
                type="button"
                className={`wo-intel-btn ${intelOpen ? 'is-active' : ''}`}
                aria-label="Site Intel"
                aria-pressed={intelOpen}
                onClick={(event) => {
                  drawerReturnFocusRef.current = event.currentTarget;
                  setAuditOpen(false);
                  setIntelOpen((prev) => {
                    const next = !prev;
                    if (next) setSelectedId(null);
                    return next;
                  });
                }}
                title="Site Intelligence: health, files, tech stack and brand"
              >
                <Activity size={13} />
                <span>Site Intel</span>
              </button>
            )}

            <div className="wo-tool-group" role="group" aria-label="View tools">
              {searchOpen ? (
                <div className="wo-search-pill">
                  <Search size={13} />
                  <input
                    type="text"
                    autoFocus
                    className="wo-search-field"
                    placeholder="Filter URL or title"
                    aria-label="Filter map by URL or title"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                  <button type="button" className="wo-search-clear" onClick={() => { setSearchQuery(''); setSearchOpen(false); }} aria-label="Clear search">
                    <X size={13} />
                  </button>
                </div>
              ) : (
                <button type="button" className="wo-icon-btn" onClick={() => setSearchOpen(true)} title="Search pages" aria-label="Search pages">
                  <Search size={15} />
                </button>
              )}
              <button type="button" className="wo-icon-btn" onClick={() => setResetSignal((n) => n + 1)} title="Reset camera" aria-label="Reset camera">
                <RotateCcw size={15} />
              </button>
              <button type="button" className="wo-icon-btn" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))} title="Toggle light/dark theme" aria-label="Toggle light/dark theme">
                {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
              </button>
              <MenuButton label="More actions" icon={<MoreHorizontal size={15} />} items={[
                ...(manifest.siteId !== PREVIEW_SITE_MANIFEST.siteId ? [{
                  id: 'dashboard', label: 'Open Site Dashboard Note', icon: <FolderGit2 size={14} />,
                  onSelect: () => activeHost.onOpenNote(`sites/${manifest.siteId}/_dashboard.md`, true),
                }] : []),
                { id: 'rotate', label: 'Gentle globe rotation', checked: autoRotate, title: 'Toggle gentle globe rotation', onSelect: () => setAutoRotate((v) => !v) },
              ]} />
            </div>
          </div>
        )}
      </header>

      {manifest && !progress.running && !auditOpen && <>
        {explorerOpen && <PageExplorer manifest={manifest} attention={attention} selectedId={selectedId} filter={filter} query={searchQuery} onQuery={setSearchQuery} onFilter={openPageFilter} onSelect={selectPage} onClose={() => setExplorerOpen(false)} />}
        {legend.length > 0 && <div className="wo-map-legend" aria-label="Map legend">{legend.map(([id, label, dot]) => <span key={id}><i className={dot} aria-hidden="true" />{label}</span>)}</div>}
      </>}

      {/* Center Minimal Onboarding Card (when 0 sites captured yet) */}
      {showOnboardingCard && (
        <div className="wo-center-overlay">
          <div className="wo-capture-card">
            <div className="wo-card-kicker">WEBSITE INTELLIGENCE FOR OBSIDIAN</div>
            <h1 className="wo-card-title">Visualize any website in full</h1>
            <p className="wo-card-sub">
              Sitemap first, then clean Markdown content and local images, then every
              internal and external link mapped onto a 3D Site Globe.
            </p>

            <form className="wo-hero-form" onSubmit={handleCaptureSubmit}>
              <input
                ref={centerInputRef}
                type="text"
                autoFocus
                className="wo-hero-input"
                placeholder="websiteexample.com"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                aria-label="Enter website domain"
              />
              <button
                type="submit"
                className="wo-hero-btn"
                disabled={!urlInput.trim()}
              >
                <span>Start</span>
                <ArrowRight size={15} />
              </button>
            </form>

            {progress.phase === 'error' && progress.error && (
              <div className="wo-error-banner">{progress.error}</div>
            )}

            <div className="wo-card-foot">
              <button
                type="button"
                className="wo-ghost-link"
                onClick={() => setManifest(PREVIEW_SITE_MANIFEST)}
              >
                Or inspect sample 3D Site Globe preview
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Independent queues report actual work rather than a page-limit percentage. */}
      {progress.running && (
        <div className="wo-center-overlay">
          <div className="wo-progress-card" role="status" aria-live="polite">
            <div className="wo-progress-head">
              <div>
                <div className="wo-card-kicker">{progress.operation === 'links' ? 'CHECKING SAVED TARGETS' : 'CAPTURING SITE INTO VAULT'}</div>
                <div className="wo-progress-domain">{progress.targetUrl}</div>
              </div>
              {activeHost.cancelCrawl && (
                <button
                  type="button"
                  className="wo-btn-secondary wo-btn-xs"
                  onClick={() => {
                    activeHost.cancelCrawl?.();
                    setProgress(IDLE_PROGRESS);
                  }}
                >
                  Cancel
                </button>
              )}
            </div>

            <p className="wo-progress-description">{progress.message}</p>
            <div className="wo-steps-list">
              <div className={`wo-step-item ${progress.phase === 'sitemap' ? 'is-active' : 'is-done'}`}>
                {progress.phase === 'sitemap' ? <Loader2 size={15} className="wo-spin" /> : <CheckCircle2 size={15} />}
                <div className="wo-step-body"><span className="wo-step-label">{progress.operation === 'links' ? 'Reuse saved capture' : 'Discover pages'}</span><span className="wo-step-meta">{progress.operation === 'links' ? 'Pages and media are kept' : `${progress.sitemapsFound} sitemap(s) · ${progress.sitemapUrlsCount} listed URLs`}</span></div>
              </div>
              {([
                ['pages', 'Pages and text'], ['media', 'Images and attachments'], ['links', 'Link checks'],
              ] as const).filter(([key]) => progress.operation !== 'links' || key === 'links').map(([key, label]) => {
                const lane = progress.pipeline?.[key];
                const active = (lane?.active ?? 0) > 0;
                const settled = lane && lane.queued === 0 && lane.active === 0 && lane.discovered > 0;
                return <div key={key} className={`wo-step-item ${active ? 'is-active' : settled ? 'is-done' : ''}`}>
                  {active ? <Loader2 size={15} className="wo-spin" /> : settled ? <CheckCircle2 size={15} /> : <span className="wo-step-bullet">·</span>}
                  <div className="wo-step-body"><span className="wo-step-label">{label}</span><span className="wo-step-meta">
                    {lane ? `${lane.completed} completed · ${lane.active} active · ${lane.queued} queued` : key === 'pages' && progress.currentPage > 0 ? `${progress.currentPage} processed` : progress.operation === 'links' ? 'Waiting for saved target list' : 'Waiting for discovery'}
                    {lane && (lane.failed > 0 || lane.skipped > 0) ? ` · ${lane.failed} unavailable · ${lane.skipped} skipped` : ''}
                  </span></div>
                </div>;
              })}
              <div className={`wo-step-item ${progress.phase === 'compile' ? 'is-active' : ''}`}>
                {progress.phase === 'compile' ? <Loader2 size={15} className="wo-spin" /> : <span className="wo-step-bullet">·</span>}
                <div className="wo-step-body"><span className="wo-step-label">{progress.operation === 'links' ? 'Save link results' : 'Save notes and map'}</span><span className="wo-step-meta">Validate files and save the snapshot</span></div>
              </div>
            </div>
            <div className="wo-progress-limits">{progress.operation === 'links' ? 'Up to 1,000 remaining targets per run with a 60 second time budget.' : `Page limit ${progress.maxPages}. Media files are separate from page totals.`}{progress.pipeline ? ` ${Math.round(progress.pipeline.elapsedSec)}s elapsed.` : ''}</div>

            {progress.currentUrl && (
              <div className="wo-progress-url" title={progress.currentUrl}>
                {progress.currentUrl}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Toast when a manifest is already open */}
      {manifest && !progress.running && progress.phase === 'error' && progress.error && (
        <div className="wo-floating-error">
          <span>{progress.error}</span>
          <button
            type="button"
            className="wo-search-clear"
            onClick={() => setProgress(IDLE_PROGRESS)}
          >
            <X size={13} />
          </button>
        </div>
      )}

      {/* Bottom bar: one segmented node filter plus a layers menu. Empty filters are left out. */}
      {manifest && !progress.running && !auditOpen && (
        <div className="wo-bottom-dock">
          <div className="wo-filter-group" role="group" aria-label="Show nodes">
            {(
              [
                ['all', 'All', counts.all, ''],
                ['hubs', 'Sections', counts.hubs, 'wo-dot-hub'],
                ['pages', 'Pages', counts.pages, 'wo-dot-page'],
                ['issues', 'Needs attention', counts.issues, 'wo-dot-broken'],
                ['orphans', 'Orphans', counts.orphans, 'wo-dot-orphan'],
                ['external', 'External', counts.external, 'wo-dot-ext'],
              ] as const
            ).filter(([id, , count]) => id === 'all' || count > 0 || filter === id).map(([id, label, count, dotClass]) => (
              <button
                key={id}
                type="button"
                className={`wo-dock-chip ${filter === id ? 'is-active' : ''}`}
                onClick={() => openPageFilter(id)}
                aria-pressed={filter === id}
              >
                {dotClass && <span className={`wo-dot ${dotClass}`} aria-hidden="true" />}
                <span>{label}</span>
                <span className="wo-dock-count">{count}</span>
              </button>
            ))}
          </div>

          <MenuButton label="Map layers" text="Layers" icon={<Layers size={14} />} placement="above" badge={layersOn} className="wo-layers-menu" items={[
            { id: 'links', label: 'All connections', checked: showAllLinks, title: 'Show all captured cross-links, or keep the map focused on site structure', onSelect: () => setShowAllLinks((value) => !value) },
            { id: 'external', label: 'External orbit', checked: showExternal, title: 'Show or hide external domains', onSelect: () => setShowExternal((v) => !v) },
            { id: 'nav', label: 'Navigation links', checked: showChromeLinks, title: 'Include header and footer menu links alongside links in the page body', onSelect: () => setShowChromeLinks((v) => !v) },
            { id: 'flow', label: 'Light flow', checked: showPulses, title: 'Subtle directional light moving along links', onSelect: () => setShowPulses((v) => !v) },
          ]} />
        </div>
      )}

      {/* 3D Orientation Gizmo */}
      {manifest && !progress.running && !auditOpen && (
        <ViewGizmo3D
          ref={gizmoRef}
          onSnapAxis={(axis) =>
            setAxisSnapRequest((prev) => ({ axis, seq: (prev?.seq ?? 0) + 1 }))
          }
        />
      )}

      {manifest && auditOpen && !progress.running && <SiteAuditPanel
        key={manifest.siteId} manifest={manifest} onClose={closePanels}
        onInspectPage={(id) => { setAuditOpen(false); selectPage(id); drawerReturnFocusRef.current = auditButtonRef.current; }}
        onOpenNote={(path) => activeHost.onOpenNote(path, true)}
        onOpenExternalUrl={(url) => activeHost.onOpenExternalUrl(url)}
        onContinueLinks={manifest.siteId === PREVIEW_SITE_MANIFEST.siteId ? undefined : () => { void handleContinueLinks(true); }}
      />}

      {/* Slide-Over Site Intelligence Drawer */}
      {manifest && intelOpen && !selectedNode && !progress.running && !auditOpen && (
        <SiteIntelDrawer
          manifest={manifest}
          isPreview={manifest.siteId === PREVIEW_SITE_MANIFEST.siteId}
          onClose={closePanels}
          onContinueLinks={() => { void handleContinueLinks(); }}
          onOpenNote={(obsPath) => activeHost.onOpenNote(obsPath, true)}
          onOpenExternalUrl={(u) => activeHost.onOpenExternalUrl(u)}
        />
      )}

      {/* Slide-Over Node Inspector */}
      {manifest && selectedNode && !progress.running && !auditOpen && (
        <InspectorDrawer
          manifest={manifest}
          node={selectedNode}
          onClose={closePanels}
          onSelectAndFly={(nid) => {
            setSelectedId(nid);
            setFlyRequest((prev) => ({ nodeId: nid, seq: (prev?.seq ?? 0) + 1 }));
          }}
          onOpenNote={(obsPath) => activeHost.onOpenNote(obsPath, true)}
          resolveAssetUrl={activeHost.resolveAssetUrl}
          onOpenExternalUrl={(u) => activeHost.onOpenExternalUrl(u)}
        />
      )}
    </div>
  );
};

export default App;
