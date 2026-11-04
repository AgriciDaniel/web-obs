# Web-Obs technical reference

This is the full reference for how Web-Obs captures, stores and verifies a site. For a short introduction, see the [README](../README.md).

Website Intelligence and 3D Site Globe plugin for Obsidian. Pure local scripts, no AI, no external API integrations or API keys.

The crawler requests public website pages, robots.txt, sitemaps, discovery files and assets directly over HTTP. Since 0.2.0 it also opens one TLS connection to the site to read its certificate, and, when the optional `dnspython` package is installed and the setting is on, asks the system DNS resolver for the domain's MX, SPF, DMARC, common DKIM selectors and CAA records. That DNS lookup is the only request that does not go to the captured site or a link found on it. External links are extracted into the graph; the direct link-check helper does not use a reputation or SEO service. Analytics tags and AI crawler policies are inspected locally, without using analytics reporting APIs or an AI provider. Domain registration, hosted DNS services, certificate transparency, PageSpeed and CrUX services are outside the product scope.

Optional browser rendering allows public documents and static resources, blocks background workers, WebRTC, WebTransport, WebSockets, background fetch/XHR, event streams and form submissions, and routes HTTP traffic through the validated Python client. Pages that depend on data APIs can therefore remain incomplete. Captured content is an observation of the accessible page, not a guarantee that every section was collected. These are tested browser controls, not an operating-system network sandbox.

Enter a single domain (`websiteexample.com`) and `web-obs` runs a capture pipeline directly into your Obsidian vault:

1. **Sitemap first:** Discovers `robots.txt` and common sitemap endpoints, recursively expanding `<sitemapindex>`, `<urlset>`, `.xml.gz` archives, RSS/Atom feeds, and `.txt` sitemaps, while checking `/llms.txt`, `/llms-full.txt`, and per-bot AI crawler rules.
2. **Content, local media, and Site Intelligence:** Crawls pages with DNS-pinned HTTP fetching (with automatic Playwright fallback for client-rendered SPAs), converts the full semantic page structure into clean Markdown (hero sections, KPI/stat rows, GFM tables, fenced code blocks, FAQs, testimonials, single-line `[[wikilinks]]`), saves images and inline `<svg>` charts locally into `sites/<domain>/assets/`, and extracts analytics/pixels (`GA4`, `GTM`, `Google Ads`, `Meta`, `Clarity`, `PostHog`, etc.), CMS/CDN & HTTP security headers, conversion funnels and per-page SEO audit signals.
3. **Direct link checks and saved topology:** Checks observed external URLs and resource targets with ordinary HEAD/GET requests and records healthy responses, confirmed 404/410 responses, server errors, access limits and unchecked targets separately. Saves every observed domain and source relationship; visual filters keep the map readable.
4. **Internal and external links + 3D Site Globe:** Separates contextual body links from global `<nav>`/`<header>`/`<footer>` and corpus-wide repeated chrome links, canonicalizes external and social domains, audits orphan and unlisted pages, and renders the entire architecture on an interactive **3D Cartographic Site Globe** inside Obsidian with the website domain at its core and calm directional light flow.

---

## Parallel capture and media

After sitemap discovery, independent page, media and link queues overlap. Spawned workers isolate network activity and reuse a browser for render tasks. A shared limiter permits at most six active requests overall and two per origin, with the configured polite interval between request starts. Only the coordinator writes vault files. Hard task deadlines and cancellation terminate owned worker processes; saved captures still pass through staging and preservation checks.

The progress card reports actual completed, active, queued, unavailable and skipped work for each lane. The page limit is a cap, not a percentage denominator. HTTP-only pages use three worker slots, browser rendering one, media two and link checks three, subject to the shared limits.

Known media suffixes and observed response MIME types classify resources separately from HTML pages. HTML landing pages such as `/audio` remain pages. Audio, video, manifests, captions, documents, fonts, stylesheets and scripts have source-page references in `_resources.json` and a readable `_resources.md`. Small captions are saved under `assets/transcripts/`; images and sanitized inline SVGs remain local. Large audio and video bodies are reference-only, including when an image-shaped URL returns an audio MIME type. Resource availability appears in the inspector and Site Intel.

Confirmed 404/410 page responses are broken. Timeouts, blocked access, server errors and incomplete extraction are unavailable, with the original response and reason retained. A successful media response never creates a broken HTTP-200 page node. On recapture, unchanged generated notes that were reclassified as media move into history; annotated and legacy notes remain protected.

Use `--serial` only for reproducible regression comparisons. `engine/.venv/bin/python3 scripts/verify-pipeline.py --benchmark --benchmark-output <report.json>` compares serial and parallel capture against the same delayed local fixture, including identical retained artifact bytes. It does not predict public-site speed.

## Site health and discovery files

Site Intel opens with a **Site health** card (crawlability, indexability, AI readiness, security, links, and performance from server signals only). Each area is a status, not a combined score. Performance uses response time, compression and HTML size as the crawler saw them, and never claims Core Web Vitals. Below it, **Discovery files** lists robots.txt, sitemaps, llms.txt (validated against llmstxt.org), llms-full.txt (a convention, not part of the spec), ai-catalog, api-catalog (RFC 9727), agent and MCP files, security.txt (RFC 9116, including expiry) and ads.txt, with a copyable starter file for anything missing. Discovery probes follow up to three redirects on the same origin; cross-origin redirects are recorded and not followed. User-triggered AI fetchers (ChatGPT-User, Claude-User, Perplexity-User) may ignore robots.txt.

Security headers are read from the homepage and compared across the sampled pages, so a header that is missing on inner pages is reported as inconsistent. IndexNow is listed as "Not detectable" because its key file name is private to each site.

## Diagnostics

Run **Web-Obs: Run diagnostics** from the command palette, or press **Run diagnostics** in settings. It checks the vault, the packaged engine files (against the build manifest), Python 3.14 and its packages, Playwright and Chromium, vault write access and outbound HTTPS. Each problem comes with a fix, and **Copy report** gives you text to paste into a bug report. It never installs anything. See `docs/TROUBLESHOOTING.md`.

Verification reports live in `docs/`.

## Local runtime requirements

Use a manually prepared Python 3.14+ environment with `requests`, `beautifulsoup4` and `lxml`. The selected `auto` or `always` rendering mode additionally needs Playwright and its Chromium executable. Select **Fast HTTP only** to capture without a browser. The plugin checks capabilities and never installs packages, creates a virtual environment, or downloads a browser automatically.

## Quick Start in Obsidian

1. Open this folder as an Obsidian vault with the plugin installed and enabled.
2. Click the **Globe** icon in the left ribbon (or run `Web-Obs: Open 3D Site Globe` from the Command Palette).
3. Type a domain such as `websiteexample.com` and click **Start**.

### Explore a saved capture

The capture summary shows the capture date, pages collected, recorded SEO flags, and discovered external domains separately from domains represented in the saved map. Missing audit metrics display **No data**.

Use the **Page explorer** to search titles and URLs, browse flagged pages or saved external domains, and open a page inspector with the keyboard. The map opens in **Structure view**, with external domains hidden. Enable **All connections**, **External Orbit**, or **Nav Links** when you need those layers. Selecting a page reveals its direct connections. The domain remains at the center and **Light Flow** retains its smaller, slower pulses.

Use the arrow keys within the layout tabs to switch between Globe, Road and Clusters. Press **Escape** to close the inspector and return focus to its trigger. Site Intel describes public-page observations, not verified analytics delivery or a complete SEO health score. Response duration is labelled separately from TTFB.

---

## Vault Output Structure

Every captured site is stored cleanly under `sites/<domain>/`:

```text
sites/<domain>/
├── _dashboard.md          # Executive overview, tech stack, AI/GEO readiness, SEO & link audit
├── _site-graph.json       # Full 3D Site Globe topology + Site Intelligence bundle
├── _site-summary.json     # Structured brand, stack, funnel & page dataset for other tools
├── _sitemap.canvas        # Native Obsidian JSON Canvas visual sitemap
├── _pages.base            # Nine Bases views with current-capture filters
├── _fetch-log.json        # Requests, skipped URLs, retained paths, hashes and evidence exclusions
├── _fetch-log.md          # Readable fetch receipts
├── _link-health.json      # Every observed external target, including unknown and unchecked
├── _link-health.md        # Direct link-check report
├── _drift-report.md       # Changes from previous capture, when available
├── _audit.md              # Site audit report: findings, link opportunities, fix list, duplicates
├── _findings.csv          # Every finding row, with a stable task ID
├── _tasks.md              # Checklist of findings; ticks survive recaptures
├── _evidence-pack.md        # Quoted website observations with exact local source references
├── _recapture-report.md   # Preserved member files and proposed generated replacements
├── _generated-files.json  # Generated and installed hashes used to detect edits
├── _raw/                  # Retained response bodies, decoded text and linked CSS evidence
├── llms.txt               # Saved locally when published by the target website
├── assets/                # Locally downloaded images, inline SVG diagrams and browser-sample screenshots
├── pages/                 # Clean Markdown notes mirroring URL paths + rich YAML frontmatter
└── _external/             # Satellite hub notes for canonicalized external domains
```

---

## 3D Visualization Modes

- **Globe:** Concentric 3D Cartographic Site Globe. The website domain name sits at the core, top-level section hubs orbit the inner shell, deeper section pages align along section meridians, orphan pages collect on the south polar ring, and external domains orbit on the outer satellite shell with subtle directional light flow.
- **Road:** Left-to-right click-depth flow (`Depth 0` homepage through deeper internal click hops and outbound external domains) showing how visitors and crawlers traverse the site.
- **Clusters:** Section-grouped pillars separating directories (`/services`, `/blog`, `/work`, etc.) into distinct spatial zones.

---

## CLI & Standalone Web Preview

### Run the Python engine directly

```bash
engine/.venv/bin/python3 engine/crawl_site.py websiteexample.com --vault . --max-pages 250
```

Options:
- `--max-pages <n>`: Maximum internal pages to crawl (default `250`).
- `--no-check-external`: Extract external links without requesting their destinations; records them as unchecked.
- `--no-images`: Skip downloading images into `sites/<domain>/assets/`.
- `--image-mode preferred|all`: Save primary images, posters and icons by default; use `all` to archive responsive variants too. All observed URLs stay in the resource inventory.
- `--continue-links`: Interpret the positional argument as a saved site ID and check its unchecked targets and confirm legacy HEAD-only missing responses. HTML and local media are reused.
- `--render auto|always|never`: Headless Chromium fallback mode for JS-heavy sites (default `auto`).
- `--delay <seconds>`: Polite delay between requests (default `0.15`).
- `--no-browser-audit`: Skip the sampled browser audit (lab timings, axe-core, screenshots, JavaScript gap, third parties).
- `--no-snapshots`: Skip full-page snapshots. `--snapshot-limit N` (default 25) caps how many pages are rendered, home and the strongest pages first; `--snapshot-html` also saves the rendered HTML under `assets/snapshots/`. Snapshots are rendered at 1280 px wide, cut at 12,000 px tall, saved as JPEG under `assets/screenshots/full-*.jpg`, and recorded on each node as `snapshot`. The viewport is set to the page height before the picture, and elements caught part way through a scroll effect are shown at rest; menus and dialogs hidden on purpose stay hidden. Skipped with Fast HTTP only.
- `--no-dns-checks`: Skip the email DNS checks.
- `--spell-check`: List possible English misspellings per page (needs `pyspellchecker`).

### Run standalone browser preview (with a local capture endpoint)

```bash
npm run dev
```

### Build and install into an Obsidian vault

```bash
npm run build
npm run install:vault
npm run verify
```

Verification uses local fixtures, mocked native lifecycle tests and actual headless Chromium. It checks the complete source, packaged and installed engine file hashes. It does not establish that every public website can be fully captured, or replace testing inside the actual Obsidian UI. Captures report known collection gaps in `_site-graph.json`, `_site-summary.json`, `_dashboard.md` and the Site Intel panel.


## Recapture safety

Captures are staged under `.web-obs/staging/`, checked, then promoted under a vault-wide lock. A failed or cancelled capture leaves the previous active capture in place. Interrupted directory promotion is recovered on the next capture. The old capture is retained under `.web-obs/history/<site>/<capture-id>/`.

Generated-file hashes distinguish unedited output from local modifications. Edited files and manually created notes survive recapture. Fresh generated replacements for edited files go under `.web-obs/proposals/`; `_recapture-report.md` lists their paths. The page inspector identifies preserved notes. On the first recapture of a legacy capture without hashes, differing files are conservatively preserved for review. History and proposals are hidden from ordinary Obsidian indexing; review them in the filesystem.

Changes detected during publication abort the promotion and preserve the active files. This protects against tested process interruptions and publication races; it is not a power-loss durability guarantee. Capturing does not alter personal graph preferences.

## Evidence and coverage

Every request sends one honest user agent, `Mozilla/5.0 (compatible; WebObs/<version>; +https://github.com/AgriciDaniel/web-obs/blob/main/docs/CRAWLER.md)`, built in `engine/url_safety.py` from the version in `engine/__init__.py`. Playwright contexts use the same string, so it never contradicts the real Chromium client hints. [CRAWLER.md](CRAWLER.md) is the page for site owners.

Politeness: a `Crawl-delay` in the matching robots group (capped at 60 seconds) makes the capture send one request at a time to that origin with at least that gap, across every phase. Worker processes are paced by their shared lease broker, and the main process by a per-origin pacer in `url_safety.py`; the pipeline bridges the hand-off in both directions. An HTTP 429, or a 503 with `Retry-After`, on a captured page pauses new requests to the site for that time (30 seconds when a 429 has none, at most 300), retries that page once, and stops requesting new pages after three such answers or a longer `Retry-After`. A bare 503 is retried once at the end of the queue without pausing, since it is often one broken page. Skipped pages are recorded with the reason.

The actual WebObs user agent is evaluated against the target origin's robots rules before pages and sitemap requests. Scheme, host or port variants obtain separate policies. Robots network/server failures and rate limiting defer crawling; skipped URLs are recorded. Third-party static assets remain direct website resource requests; their robots policies are not comprehensively audited.

Direct link checks have a default budget of 1,000 observed targets. They overlap collection, then have a 30-second drain budget after the page frontier settles. Asset GET results are reused rather than checked again. Every observed target receives a result row, including targets left unchecked. Use **Site Intel > Check remaining targets** to continue unchecked results and confirm legacy HEAD-only 404/410 responses without recrawling pages or downloading media bodies. Each continuation has a 1,000-target and 60-second budget, retains previous results and page capture time, and records a separate update time and engine/configuration receipt. Repeating it can cover additional targets; access restrictions can remain inconclusive. Edited reports are preserved with fresh proposals. A request attempt is not proof of health. HTTP 403/429 and network failures stay inconclusive. These checks do not verify a complete cross-domain backlink profile.

Page responses are limited to 5 MB, with a 128 MB raw page-body budget per capture; saved images, inline SVGs and captions share a 500-file and 128 MB budget; captions have a 1 MB per-file limit and images a 12 MB per-file limit. Graphs exceeding 20,000 nodes or 200,000 edges are refused before promotion; stored relationships are never silently sampled to fit. Sitemap expansion has explicit declared/child/URL limits, reported as collection warnings. Brand declarations sample up to five linked stylesheets and retain the full selected source with sampling metadata. Asset omissions caused by count or byte limits produce an explicit aggregate warning and a partial snapshot. Unselected responsive variants in preferred mode are intentional and marked `not-selected`. A partial snapshot describes known collection gaps; preserved note edits are reported separately.

Fetch receipts bind source paths to SHA-256 hashes. Original decoded HTTP response bodies, rendered DOM and UTF-8 decoding sidecars have separate evidence labels. The evidence pack exports exact source spans with local locators and explicit exclusions, and separates design inferences from observations. It does not write into another vault or approve commercial claims.

The internal link score is a relative weighted graph heuristic. Drift compares observed hashes, metadata and URL-based edges. The resource inventory is bounded at 20,000 URLs with explicit truncation warnings. An absent page is unobserved, and does not become a confirmed deletion merely because a later crawl was partial.

If WebGL cannot initialize, the app displays a graphics fallback while preserving capture controls, the explorer and report access. Reopen the view after restoring graphics support to retry the 3D renderer.


For native acceptance testing, `scripts/verify-native-ui.py --port <local-CDP-port> --vault <isolated-test-vault> --evidence <output-directory>` attaches to a separately launched Obsidian instance. It checks the exact vault path before acting, starts only local HTTP fixtures, captures through the real plugin UI, opens Markdown notes and renders the generated Bases file. Add `--render-mode auto --spa-fixture --media-fixture` to exercise native browser rendering, caption storage and the independent progress lanes. Add `--expect-no-webgl` to exercise the graphics fallback. It is separate from `npm run verify`, which does not launch or modify an Obsidian desktop session.

Browser discovery uses the exact Chromium revision expected by the selected Python Playwright package. If Obsidian's Flatpak cache has no matching executable, the engine checks the standard user browser cache and launches that resolved file explicitly. An existing `PLAYWRIGHT_BROWSERS_PATH` setting remains authoritative. No browser is downloaded automatically. Use `engine/.venv/bin/python3 scripts/verify-browser-runtime.py --flatpak` to exercise actual Flatpak Auto rendering with a local SPA fixture. Native acceptance supports `--render-mode auto --spa-fixture` to test readiness and rendering together.

Browser rendering currently requires the full Playwright Chromium installation. A headless-shell-only (`--only-shell`) installation is not selected by this resolver. Empty browser-path environment values use normal discovery; nonempty overrides, including `0`, remain authoritative.

Technology and analytics observations record a sample of at most eight captured HTML pages, with selected source URLs and the full HTML page denominator. Security header observations cover the homepage response only. Missing detections are limited to that sample. New captures retain requested options, limit values, local Python/package versions and engine source hashes in `captureProvenance`; legacy captures remain readable without invented provenance. Canvas exports include every captured internal page, including groups larger than 32 pages.

## Page checks and site audit

Each captured HTML page gets deterministic checks in `engine/page_checks.py`: text to HTML ratio, readability (English only, 100 words or more), title and description relevance, doctype and charset, duplicate meta tags, meta refresh, deprecated tags, mixed content, render-blocking resources (scripts in the head without `async`, `defer` or `type=module`, and stylesheets without a non-screen `media`), DOM size, depth and widest element (Lighthouse thresholds of 1,500 nodes, 32 levels and 60 children), URL quality, Open Graph and Twitter tags, cache and compression headers, microdata and RDFa types, static accessibility counts, citability signals and keyword density. Results are stored per page as `pageChecks`, and issue slugs join `seoIssues`. `issueCatalog` in the manifest gives each slug a title, category, tone and explanation.

`engine/site_audit.py` works across the capture: duplicates (exact by content hash, near by 64-bit SimHash over word 3-shingles with a Hamming distance of 4 or less), the internal link fix list, internal link opportunities (a target's H1 or title phrase of two to six words appearing in another page's visible text without a link; phrases found on more than 30% of pages are skipped as boilerplate), conflicting signals, weak pages, cannibalization, anchor conflicts, crawl traps, freshness (older than 365 days), trust pages, structured data rules summarized from Google Search Central, image weight (300 KB and up) and legacy formats, sitemap limits and robots.txt syntax. All findings share one shape (`id`, `category`, `tone`, `title`, `explanation`, `targets`) and are stored in `audit.findings`.

`engine/transport_checks.py` reads the TLS certificate, judges HSTS, Content Security Policy and cookie flags from the homepage response, and runs the optional email DNS checks. `engine/browser_audit.py` opens up to five healthy pages (the homepage, then the highest relative link scores) in the same guarded browser used for rendering, with a 90-second budget. It records lab timings, the difference between raw and rendered HTML, axe-core violations, a screenshot and third-party hosts and script cookies on first load. The capture proxy strips `Set-Cookie`, so only cookies set by scripts are visible there. axe-core is vendored in `engine/vendor/` under MPL-2.0.

`_tasks.md` gives each finding target a stable ID (`^wo-` plus a hash of the finding and URL). On recapture the previous file is read first: ticks are kept, tasks no longer observed move to Resolved, and tasks for pages a partial capture did not revisit stay as they were. This file is always regenerated rather than preserved as a member edit, because it already carries the member's ticks forward.

## Site audit and visual evidence

Use **Site audit** in the Web-Obs toolbar for destination-status charts, captured pages by section, media download states and a searchable category inbox. Expand a finding to inspect its captured page, source, note or URL. The view reads the saved capture without making another scan. Escape or a layout tab returns to the map.

The panel adapts useful audit presentation ideas from Safi Site Audit. It is an independent Web-Obs view, not the Safi scanner or its full 94-rule set. It does not call PageSpeed Insights. Core Web Vitals field data, a full accessibility audit (axe-core on a sample covers automated rules only), E-E-A-T judgement, cookie consent and legal compliance remain explicitly unassessed. Header observations cover the homepage response only.

HEAD 404/410 responses are confirmed through a streamed GET before being reported missing. The fallback does not consume the response body. Legacy HEAD-only missing results can be confirmed with the same remaining-target action. Inconclusive access and transport responses stay visible.

Resource `sourceSha256` and `sourceBytes` describe downloaded bytes; saved `sha256` and `bytes` describe the retained file after sanitization. Preserved member-edited assets record their actual installed hash and a fresh proposal path. URL inventory counts exclude generated inline SVG assets, which contribute to the total local image count.
