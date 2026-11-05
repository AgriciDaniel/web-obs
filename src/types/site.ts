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

export interface PageSnapshot {
  /** Vault path relative to the site folder, for example assets/screenshots/full-about-1a2b3c.jpg. */
  screenshot: string;
  html?: string | null;
  heightPx?: number | null;
  truncated?: boolean;
  /** Height the image was cut at, in px. Missing on captures before this was recorded (they used 12000). */
  capPx?: number | null;
  /** Pinned overlays, such as cookie banners, hidden for the snapshot. */
  hiddenOverlays?: number | null;
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
  /** Full-page snapshot saved by the capture, when one was taken. */
  snapshot?: PageSnapshot;
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
  /** Added in schema 1.3.0: deterministic document checks for this page. */
  pageChecks?: PageChecks | null;
  simhash?: string;
  keywords?: PageKeywords;
}

export interface KeywordRow { term: string; count: number; density?: number; pages?: number }
export interface PageKeywords { totalWords?: number; unigrams?: KeywordRow[]; bigrams?: KeywordRow[]; trigrams?: KeywordRow[] }

export interface PageReadability {
  fleschReadingEase: number;
  fleschKincaidGrade: number;
  automatedReadabilityIndex: number;
  colemanLiauIndex: number;
  smogIndex?: number | null;
  sentences: number;
  wordsPerSentence: number;
  note?: string;
}

export interface PageChecks {
  textRatio?: number;
  textChars?: number;
  htmlBytes?: number;
  readability?: PageReadability | null;
  titleRelevance?: number | null;
  descriptionRelevance?: number | null;
  titleLength?: number;
  descriptionLength?: number;
  doctype?: boolean;
  metaCharset?: string | null;
  headerCharset?: string | null;
  charsetMismatch?: boolean;
  duplicateMetaTags?: string[];
  metaRefresh?: string | null;
  deprecatedTags?: string[];
  frames?: boolean;
  flash?: boolean;
  placeholderText?: boolean;
  insecureLinks?: string[];
  mixedContent?: string[];
  scripts?: { total: number; external: number; renderBlocking: string[] };
  stylesheets?: { total: number; renderBlocking: string[] };
  dom?: { nodes: number; maxDepth: number; maxChildren: number; widestElement?: string };
  url?: { length: number; pathLength: number; queryParams: string[]; hasUppercase: boolean; hasUnderscore: boolean; nonAscii: boolean; doubleSlash: boolean };
  openGraph?: Record<string, string>;
  twitter?: Record<string, string>;
  firstImageLazy?: boolean;
  cache?: { cacheControl: string | null; maxAge: number | null; cacheable: boolean; noStore: boolean; noCache: boolean; etag: boolean; lastModified: string | null; contentEncoding: string | null };
  microdataTypes?: string[];
  rdfaTypes?: string[];
  accessibility?: { unlabeledInputs: number; unnamedButtons: number; emptyLinks: number; note?: string };
  citability?: { questionHeadings: number; headingsChecked: number; lists: number; tables: number; faqBlocks: number; paragraphs: number; avgParagraphWords: number; longParagraphs: number; answerFirst: boolean; note?: string };
  htmlValidation?: { errors: number; topCodes: Array<{ code: string; count: number }>; validator: string } | null;
  spelling?: { checkedWords: number; possibleMisspellings: string[]; note?: string } | null;
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
  auditFindings?: number;
  auditFindingItems?: number;
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

export interface LlmsTxtNote { line: number; code: string; level: 'error' | 'warn' | 'info'; message: string }

/** llms.txt checked against the llmstxt.org format. Only `error` notes make it invalid. */
export interface LlmsTxtValidation {
  valid: boolean;
  issues: string[];
  notes?: LlmsTxtNote[];
  title?: string | null;
  summary?: string | null;
  sections?: Array<{ name: string; line: number; links: number }>;
  hasOptional?: boolean;
  stats?: { bytes: number; approxTokens: number; sections?: number; links?: number; sameSiteLinks?: number; externalLinks?: number; markdownLinks?: number; linksWithNotes?: number };
  contentType?: string | null;
  convention?: boolean;
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
  validation?: Record<string, LlmsTxtValidation & { expires?: string | null }>;
  /** Whether the llms.txt checks got an answer: found, absent (404/410), html, unavailable, refused or not-checked. */
  llmsProbe?: Record<string, { state: 'found' | 'absent' | 'html' | 'unavailable' | 'refused' | 'not-checked'; statusCode?: number; detail?: string; contentType?: string | null; truncated?: boolean }>;
  llmsLinks?: Array<{ url: string; line: number; section: string; title: string; sameSite: boolean; state: 'ok' | 'redirect' | 'broken' | 'unavailable' | 'noindex' | 'non-canonical' | 'blocked' | 'external' | 'unchecked'; detail: string; statusCode?: number | null }>;
  llmsDraft?: { text: string; pages: number; hasSummary: boolean; markdownLinks: number; path?: string };
  describedBy?: string[];
  markdownAlternatePages?: number;
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

export type EngineFindingTone = 'attention' | 'review' | 'coverage';
export interface EngineFindingTarget { url: string; detail?: string; sourceUrl?: string }
export interface EngineFinding {
  id: string;
  category: string;
  tone: EngineFindingTone;
  title: string;
  explanation: string;
  targets: EngineFindingTarget[];
  targetCount?: number;
}

export interface IssueCatalogEntry { category: string; tone: EngineFindingTone; title: string; explanation: string }

export interface SiteAuditData {
  version?: number;
  findings: EngineFinding[];
  duplicates?: {
    titles: Array<{ value: string; urls: string[] }>;
    descriptions: Array<{ value: string; urls: string[] }>;
    h1?: Array<{ value: string; urls: string[] }>;
    exactContent: Array<{ urls: string[] }>;
    nearContent: Array<{ urls: string[]; similarity: number }>;
    note?: string;
  };
  linkFixes?: Array<{ sourceUrl: string; linkedUrl: string; targetUrl: string; problem: string; anchor?: string; zone?: string }>;
  linkOpportunities?: Array<{ sourceUrl: string; targetUrl: string; phrase: string; context?: string }>;
  conflicts?: Array<{ url: string; type: string; detail: string }>;
  weakPages?: { singleInlink: string[]; deadEnds: string[]; noBodyOutlinks: string[]; deep: Array<{ url: string; clickDepth: number }>; nofollowInternal: Array<{ sourceUrl: string; targetUrl: string }> };
  cannibalization?: Array<{ basis: string; term: string; urls: string[] }>;
  anchorConflicts?: Array<{ anchor: string; targets: string[] }>;
  crawlTraps?: Array<{ pattern: string; count: number; path?: string; parameters?: string[]; sample?: string[] }>;
  keywords?: { unigrams: KeywordRow[]; bigrams: KeywordRow[]; trigrams: KeywordRow[] };
  freshness?: { stale: Array<{ url: string; date: string; ageDays: number }>; undated: string[]; undatedCount: number; datedCount: number; staleAfterDays: number; oldest: { url: string; date: string } | null; newest: { url: string; date: string } | null };
  trust?: { about: string | null; contact: string | null; privacy: string | null; terms: string | null; legalLinks?: Record<string, string>; authorPages: string[]; pagesWithAuthor: number; pagesWithDate: number; pagesChecked: number; note?: string };
  schema?: { eligibility: Array<{ url: string; type: string; missingRequired: string[]; missingRecommended: string[]; eligible: boolean }>; mismatches: Array<{ url: string; type: string; detail: string }>; note?: string };
  images?: { oversized: Array<{ url: string; bytes: number; pages: string[] }>; legacyFormats: Array<{ url: string; format: string; bytes: number; pages: string[] }>; thresholdBytes?: number; note?: string };
  sitemapLimits?: { overUrlLimit: string[]; overSizeLimit: string[]; otherHostUrls: string[]; nonCanonicalUrls: string[]; note?: string };
  robotsSyntax?: { issues: Array<{ line: number; issue: string }>; issueCount: number };
  tasks?: { open: number; ticked: number; resolved: number; notRechecked: number };
}

export interface BrowserAuditPage {
  url: string;
  error?: string | null;
  screenshot?: string | null;
  lab?: { lcpMs?: number | null; cls?: number | null; domContentLoadedMs?: number | null; loadMs?: number | null; requests?: number; transferBytes?: number; note?: string } | null;
  jsGap?: { rawWords: number; renderedWords: number; rawLinks: number; renderedLinks: number; rawSchemaTypes: string[]; renderedSchemaTypes: string[]; rawH1: string[]; renderedH1: string[]; wordsAddedByJsPct: number } | null;
  a11y?: { state: string; engine?: string; detail?: string; violations?: Array<{ id: string; impact?: string | null; help: string; nodes: number }>; passes?: number } | null;
  thirdParty?: { hosts: Array<{ host: string; requests: number; category: string }>; cookies: Array<{ name: string; domain: string; firstParty: boolean; secure: boolean; httpOnly: boolean; sameSite?: string }>; note?: string } | null;
}

export interface BrowserAuditResult {
  state: 'ok' | 'skipped' | 'partial' | string;
  detail?: string;
  elapsedSec?: number;
  sampledUrls?: string[];
  budgetSkippedUrls?: string[];
  pages?: BrowserAuditPage[];
  findings?: EngineFinding[];
}

export interface TlsCertificateResult {
  state: string;
  detail?: string;
  issuer?: string | null;
  subject?: string | null;
  notBefore?: string | null;
  notAfter?: string | null;
  daysRemaining?: number | null;
  tlsVersion?: string | null;
  san?: string[];
  coversWww?: boolean | null;
  verified?: boolean;
  error?: string | null;
}

export interface HeaderQualityResult {
  hsts?: { present: boolean; maxAge: number | null; includeSubDomains: boolean; preload: boolean; preloadReady: boolean; issues: string[] } | null;
  csp?: { present: boolean; reportOnly: boolean; directives: Record<string, string[]>; issues: string[] } | null;
  cookies?: Array<{ name: string; secure: boolean; httpOnly: boolean; sameSite: string | null; issues: string[] }>;
  otherIssues?: string[];
  error?: string;
}

export interface EmailDnsResult {
  state: string;
  detail?: string;
  domain?: string;
  mx?: string[];
  spf?: { present: boolean; record: string | null; allQualifier?: string | null; lookupCount?: number; issues: string[] } | null;
  dmarc?: { present: boolean; record: string | null; policy?: string | null; subdomainPolicy?: string | null; pct?: number | null; rua?: string[] | boolean | null; issues: string[] } | null;
  dkim?: { checkedSelectors: string[]; found: string[]; note?: string };
  caa?: string[];
  note?: string;
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
  browserAudit?: BrowserAuditResult;
  snapshots?: { state: string; detail?: string; limit?: number; elapsedSec?: number; notChosen?: number; budgetSkipped?: string[]; note?: string };
  transport?: { tls?: TlsCertificateResult; headerQuality?: HeaderQualityResult; emailDns?: EmailDnsResult };
  pageCheckFeatures?: Record<string, { state: string; detail: string }>;
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
  /** Added in schema 1.3.0. */
  audit?: SiteAuditData;
  issueCatalog?: Record<string, IssueCatalogEntry>;
  linkHealth?: ExternalLinkHealth;
  robotsPolicy?: { state: string; canCrawl: boolean; reason: string; statusCode?: number | null };
  resources?: SiteResource[];
  captureProvenance?: { engineSha256: string; configuration: Record<string, unknown>; runtime: { pythonVersion: string; platform: string } };
  pipelineMetrics?: { elapsedSec: number; pages: number; resources: number; imagesBytes: number };
  brandKit?: {
    colorTokens?: unknown[];
    palette?: unknown[];
    typography?: { primaryFamilies?: string[] };
    themeColor?: string | null;
    logoUrls?: string[];
    faviconUrls?: string[];
    localLogoAsset?: string | null;
    localFaviconAsset?: string | null;
  };
  drift?: { hasChanges: boolean; contentChangesCount?: number; fileChangesCount?: number } | null;
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
  browserAudit?: boolean;
  spellCheck?: boolean;
  dnsChecks?: boolean;
  pageSnapshots?: boolean;
  snapshotLimit?: number;
  snapshotHtml?: boolean;
  tlsCheck?: boolean;
  taskList?: boolean;
  /** One time limit for every network phase, in seconds (1 to 86400). Unset or 0 means no limit. */
  deadlineSec?: number;
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
  /** Turns a vault file path into a URL the view can display, such as a saved screenshot. */
  resolveAssetUrl?: (vaultRelativePath: string) => string | null;
  /**
   * Reads a saved image from the vault as bytes, for drawing into WebGL. A resource URL from another
   * origin would taint the canvas, so the map loads its logo this way. Optional: without it the map
   * shows the brand's initials instead.
   */
  readAssetBytes?: (vaultRelativePath: string) => Promise<ArrayBuffer | null>;
  onOpenExternalUrl: (url: string) => void;
  subscribeHostEvents?: (handlers: HostEventHandlers) => () => void;
  onWebGLContextLost?: () => void;
}
