export type ThemeMode = 'light' | 'dark';

export type GlobeViewMode = 'globe' | 'road' | 'clusters';

export type NodeKind = 'home' | 'hub' | 'page' | 'external-domain';

export type NodeHealth =
  | 'home'
  | 'hub'
  | 'healthy'
  | 'orphan'
  | 'unlisted'
  | 'redirect'
  | 'broken'
  | 'unavailable'
  | 'external';

export type EdgeKind =
  | 'sitemap-hierarchy'
  | 'internal-body'
  | 'internal-chrome'
  | 'external';

export type CameraAxisSnap = '+X' | '-X' | '+Y' | '-Y' | '+Z' | '-Z';

export type NodeFilter =
  | 'all'
  | 'hubs'
  | 'pages'
  | 'orphans'
  | 'issues'
  | 'external';

export interface SiteSectionSummary {
  id: string;
  label: string;
  pageCount: number;
}

export interface SiteSitemapInfo {
  url: string;
  source: string;
  kind: string;
  url_count: number;
  child_count: number;
}

export interface SiteNode {
  id: string;
  kind: NodeKind;
  health: NodeHealth;
  title: string;
  url: string;
  path: string;
  section: string;
  obsidianPath: string;
  statusCode: number;
  /** Duration of the final request only (connect to last body byte). Redirect hops are excluded. */
  responseTimeMs?: number;
  /** Time to the first response byte of the final request. */
  ttfbMs?: number;
  /** Total fetch time including every redirect hop. */
  fetchDurationMs?: number;
  redirectHops?: number;
  /** Independent page statuses, for example unlisted, orphan, redirect, noindex. */
  flags?: string[];
  linkFormMismatches?: { linked: string; published: string }[];
  htmlBytes?: number;
  inSitemap: boolean;
  urlDepth: number;
  clickDepth: number | null;
  wordCount: number;
  readingTimeMin?: number;
  metaDescription: string;
  canonical: string;
  metaRobots: string;
  lang?: string;
  author?: string;
  publishedDate?: string;
  modifiedDate?: string;
  h1: string[];
  h2Count: number;
  schemaTypes: string[];
  imagesCount: number;
  localImagesCount: number;
  imagesMissingAlt?: number;
  imagesEmptyAlt?: number;
  templateHeadingSkips?: number;
  tablesCount?: number;
  codeBlocksCount?: number;
  formsCount?: number;
  videosCount?: number;
  audioCount?: number;
  transcriptsCount?: number;
  resourceIds?: string[];
  fetchStatus?: string;
  error?: string | null;
  seoIssues?: string[];
  coverAsset?: string | null;
  inlinksBody: number;
  inlinksTotal: number;
  outlinksBody: number;
  outlinksTotal: number;
  externalDomainsOut: number;
  externalUrlsSample?: string[];
  nofollowCount?: number;
  authorityScore?: number;
  contentHash?: string;
  rawPath?: string | null;
  noteStatus?: 'preserved-local-edits';
  proposedNotePath?: string;
  renderUsed: boolean;
}

export interface SiteEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  zone?: 'body' | 'chrome';
  anchor?: string;
  targetUrl?: string;
  count?: number;
  rel?: string[];
}

export interface SiteStats {
  pagesCrawled: number;
  sitemapsFound: number;
  sitemapUrlsTotal: number;
  internalEdges: number;
  externalDomains: number;
  externalEdges: number;
  localImagesDownloaded: number;
  orphanPages: number;
  unlistedPages: number;
  brokenOrRedirectPages: number;
  pagesWithSeoIssues?: number;
  avgResponseTimeMs?: number;
  medianResponseTimeMs?: number;
  avgFetchDurationMs?: number;
}

export interface SiteTechStackIntel {
  coverage?: { sampledPages: number; capturedHtmlPages: number; sourceUrls: string[]; selection: string; securityHeadersScope: string };
  analyticsAndPixels: Array<{ name: string; category: string }>;
  measurementIds: {
    ga4: string[];
    gtm: string[];
    googleAds: string[];
  };
  searchConsoleVerifiedMeta: boolean;
  bingVerifiedMeta: boolean;
  cmsOrFramework: string[];
  hostingAndCdn: string[];
  httpCompression?: string | null;
  cacheControl?: string | null;
  securityHeaders: {
    present: string[];
    missing: string[];
    /** Added after v0.1.0 captures: the same headers compared across sampled pages. */
    consistency?: {
      sampledPages: number;
      headers: { header: string; presentOn: number; of: number; state: 'all' | 'some' | 'none'; missingOn: string[] }[];
      inconsistent: string[];
      notes: string[];
    };
  };
}

export interface SiteAiReadinessIntel {
  endpoints: {
    llmsTxt: boolean;
    llmsFullTxt: boolean;
    aiCatalogJson: boolean;
    securityTxt: boolean;
    adsTxt: boolean;
    apiCatalog?: boolean;
    agentJson?: boolean;
    mcpJson?: boolean;
    humansTxt?: boolean;
    webManifest?: boolean;
  };
  validation?: Record<string, { valid: boolean; issues: string[]; expires?: string | null }>;
  userTriggeredBots?: string[];
  siteChecks?: Record<string, { state: 'ok' | 'warn' | 'fail' | 'skipped' | 'not-resolving' | 'unreachable'; detail: string; statusCode?: number }>;
  robotsFindings?: { blanketDisallow: boolean; blocksAssets: string[]; hasSitemapLine: boolean; contentSignal?: string | null };
  sitemapHygiene?: {
    broken: string[];
    unavailable: string[];
    redirect: string[];
    noindex: string[];
    undeclaredSitemaps: string[];
    redirectChains?: string[];
    lastmodMismatch?: string[];
    hreflangNonReciprocal?: string[];
    declaredInRobots?: number;
  };
  savedFiles: string[];
  aiBotsPolicy: Record<string, string>;
  allowedAiBotsCount: number;
  blockedAiBots: string[];
}

export interface SiteIntelBundle {
  brandName?: string;
  languages?: string[];
  rssFeeds?: string[];
  avgResponseTimeMs?: number;
  totalAssetsMb?: number;
  contacts?: {
    emails: string[];
    phones: string[];
    socialProfiles: string[];
  };
  techStack?: SiteTechStackIntel;
  aiReadiness?: SiteAiReadinessIntel;
  funnel?: {
    formsCount: number;
    videosCount: number;
    downloadsCount: number;
    platforms: Array<{ platform: string; category: string; urls: string[] }>;
  };
  domainRegistration?: {
    registeredDate: string | null;
    expirationDate: string | null;
    updatedDate: string | null;
    domainAgeYears: number | null;
    registrar: string | null;
  };
}

export interface ExternalLinkHealth {
  totalCount: number;
  checkedCount: number;
  uncheckedCount: number;
  unknownCount: number;
  assessedCount: number;
  coverageComplete: boolean;
  updatedAt?: string;
  results: Array<{ url: string; method?: string | null; status: 'ok' | 'broken' | 'server-error' | 'unknown' | 'unchecked'; statusCode: number | null; reason: string }>;
  brokenLinks: unknown[];
  serverErrors: unknown[];
  unknownLinks: unknown[];
}

export type ResourceType = 'image' | 'audio' | 'video' | 'transcript' | 'document' | 'font' | 'stylesheet' | 'script' | 'other';

export interface SiteResource {
  id: string;
  url: string;
  type: ResourceType;
  mimeType?: string | null;
  references: Array<{ pageUrl: string; role: string; label?: string | null; language?: string | null }>;
  statusCode?: number | null;
  checkStatus?: string | null;
  downloadState?: string | null;
  localPath?: string | null;
  bytes?: number;
  sha256?: string | null;
  sourceBytes?: number;
  sourceSha256?: string | null;
  localFileStatus?: string | null;
  proposedLocalPath?: string | null;
  error?: string | null;
}

export interface PipelineLane {
  discovered: number;
  completed: number;
  active: number;
  queued: number;
  failed: number;
  skipped: number;
  bytes?: number;
}

export interface PipelineProgress {
  pages: PipelineLane;
  media: PipelineLane;
  links: PipelineLane;
  elapsedSec: number;
  stage: string;
}

export interface SiteGraphManifest {
  schemaVersion: string;
  captureStatus?: 'complete' | 'partial';
  preservationStatus?: 'conflicts';
  captureWarnings?: string[];
  /** Broken things the capture found, such as a 404 image. They do not make the capture partial. */
  captureFindings?: string[];
  siteId: string;
  domain: string;
  brandName?: string;
  origin: string;
  capturedAt: string;
  elapsedSec: number;
  stats: SiteStats;
  siteIntel?: SiteIntelBundle;
  linkHealth?: ExternalLinkHealth;
  robotsPolicy?: { state: string; canCrawl: boolean; reason: string; statusCode?: number | null };
  resources?: SiteResource[];
  captureProvenance?: { engineSha256: string; configuration: Record<string, unknown>; runtime: { pythonVersion: string; platform: string } };
  pipelineMetrics?: { elapsedSec: number; pages: number; resources: number; imagesBytes: number };
  brandKit?: { colorTokens?: unknown[]; palette?: unknown[]; typography?: { primaryFamilies?: string[] } };
  drift?: { hasChanges: boolean; contentChangesCount?: number } | null;
  sitemaps: SiteSitemapInfo[];
  sections: SiteSectionSummary[];
  nodes: SiteNode[];
  edges: SiteEdge[];
}

export interface SiteSummaryItem {
  siteId: string;
  domain: string;
  capturedAt: string;
  pagesCrawled: number;
  externalDomains: number;
}

export interface CrawlOptions {
  url: string;
  maxPages?: number;
  downloadImages?: boolean;
  renderMode?: 'auto' | 'always' | 'never';
  imageMode?: 'preferred' | 'all';
  continueLinksSiteId?: string;
}

export interface CrawlProgressState {
  operation?: 'capture' | 'links';
  running: boolean;
  targetUrl: string;
  phase: 'idle' | 'sitemap' | 'crawl' | 'compile' | 'done' | 'error' | 'cancelled';
  message: string;
  sitemapsFound: number;
  sitemapUrlsCount: number;
  currentPage: number;
  maxPages: number;
  currentUrl: string;
  error?: string | null;
  pipeline?: PipelineProgress;
}

export type GlobePluginCommand =
  | { type: 'set-view-mode'; viewMode: GlobeViewMode }
  | { type: 'focus-capture-input' }
  | { type: 'select-node'; nodeId: string; fly?: boolean }
  | { type: 'reload-sites'; selectSiteId?: string };

export interface HostEventHandlers {
  onThemeChange?: (theme: ThemeMode) => void;
  onPauseChange?: (paused: boolean) => void;
  onSitesChanged?: (sites: SiteSummaryItem[], latestManifest?: SiteGraphManifest) => void;
  onCrawlProgress?: (progress: CrawlProgressState) => void;
  onCommand?: (command: GlobePluginCommand) => void;
}

export interface SiteHostAdapter {
  mode: 'obsidian' | 'standalone';
  vaultName: string;
  initialTheme?: ThemeMode;
  initialViewMode?: GlobeViewMode;
  listSites: () => Promise<SiteSummaryItem[]>;
  loadSiteManifest: (siteId: string) => Promise<SiteGraphManifest | null>;
  startCrawl: (options: CrawlOptions) => Promise<SiteGraphManifest | null>;
  cancelCrawl?: () => void;
  onOpenNote: (vaultRelativePath: string, splitPane?: boolean) => void;
  onOpenExternalUrl: (url: string) => void;
  subscribeHostEvents?: (handlers: HostEventHandlers) => () => void;
  onWebGLContextLost?: () => void;
}
