# Changelog

## 0.2.0 - 2026-11-03

A much deeper audit. Every check still runs on your computer and talks only to the site you capture, with two stated exceptions below.

### Added: page checks
- **Content:** text to HTML ratio, thin content, English readability (Flesch, Flesch-Kincaid, ARI, Coleman-Liau, SMOG), whether the title and description words appear in the body, top phrases per page, and citability signals (question headings, lists, tables, answer-first opening, paragraph length).
- **Document hygiene:** doctype, declared charset and header mismatch, duplicate meta tags, meta refresh redirects, deprecated tags, frames, Flash, placeholder text, HTML over 3 MB, missing `lang`.
- **Performance from the HTML:** render-blocking scripts and stylesheets, script and stylesheet counts, DOM size, depth and widest element (Lighthouse thresholds), compression and cache headers per page, a lazy-loaded first image, images without dimensions.
- **Security in the page:** mixed content and links to plain `http://` addresses.
- **URLs:** length, query parameters, uppercase, underscores, non-ASCII characters and double slashes.
- **Social tags:** the full Open Graph and Twitter inventory, a missing `og:image`, and `og:url` that disagrees with the canonical.
- **Accessibility from the HTML:** form fields without labels, buttons without names, links without text.
- **Microdata and RDFa** types are detected alongside JSON-LD.
- Optional: HTML parse errors (with `html5lib`) and possible English misspellings (with `pyspellchecker`, off by default).

### Added: site audit
- **Duplicates:** shared titles, descriptions and H1s, identical content, and near duplicates found with SimHash.
- **Link graph:** a fix list of internal links that point at redirects, 404s or non-canonical URLs, with the page that holds each link; internal link opportunities (a page mentions another page's title but does not link to it); pages with one inlink, dead ends, deep pages and internal nofollow links; one anchor text used for different pages.
- **Conflicting signals:** canonicals that point at redirects, errors or noindex pages, canonical chains and loops, noindex combined with a canonical elsewhere, non-canonical URLs in the sitemap, hreflang on canonicalized pages.
- **Topics:** pages competing for the same heading terms or focus phrase, with the brand name excluded, and the top phrases across the site.
- **Crawl traps:** query parameter explosions, calendar archives, session IDs, repeating and very deep paths.
- **Freshness and trust:** stale and undated pages; About, Contact, Privacy and Terms pages; author bylines.
- **Structured data:** required and recommended properties per Google rich result type, plus markup that describes content the page does not show (FAQ questions, product names, breadcrumbs that are not ancestors of the URL, article headlines).
- **Files:** sitemap size and URL limits, sitemap URLs on other hosts, robots.txt syntax notes, image weight and legacy formats from the downloaded bytes.

### Added: certificate, headers and email
- TLS certificate check: issuer, expiry countdown, TLS version, host coverage and verification.
- Header quality, not just presence: HSTS preload readiness, Content Security Policy gaps and cookie flags.
- security.txt expiry countdown.
- Email DNS (MX, SPF, DMARC, common DKIM selectors, CAA) through your system DNS resolver, with the optional `dnspython` package. This is the first check that asks a DNS resolver directly. Turn it off in settings.

### Added: browser sample
- After capture, up to five pages open in the guarded headless browser: lab LCP, CLS and load timings, words, links and schema added by JavaScript, automated accessibility rules with axe-core 4.14.0 (bundled, MPL-2.0), a screenshot, and third-party hosts and script cookies seen before any interaction. Lab numbers are one load on your machine, not field data. Turn it off in settings.

### Added: vault output
- `_audit.md` report, `_findings.csv` export, and a **Page Audit** section at the end of every page note.
- `_tasks.md`: every finding as a checkbox. Ticks are kept across recaptures, and a task closes by itself when the next capture no longer observes it. Tasks for pages a partial capture did not visit stay open.
- The change report now covers meta descriptions, canonicals, pages that became noindex, removed structured data, new page issues, robots.txt and llms.txt diffs, and homepage security headers.
- Four new Bases views: Content Quality, Duplicates, Link Opportunities and Thin Pages. New note properties: `findings_count`, `text_ratio`, `readability`, `dom_nodes`, `duplicate`, `link_opportunities`.
- **Web-Obs: Compare two captured sites** writes a side-by-side note under `sites/_compare/`.
- Settings for the browser sample, email DNS checks and spell check. CLI flags: `--no-browser-audit`, `--no-dns-checks`, `--spell-check`.

### Added: llms.txt, checked in full
- **The whole [llmstxt.org](https://llmstxt.org/) format, line by line:** one H1 title first (the only required part, after an optional byte order mark), the summary blockquote right after it, no headings before the first H2, and file list items as `- [name](url): notes`. It flags `*` or `+` bullets the reference parser skips, links that are not at the start of an item, notes without the `:`, empty sections, duplicate and non-web links, relative links, near misses of `## Optional`, and the content type. Each note says its line and whether it breaks the format, may be misread, or is the spec's writing guidance.
- **Its links, checked against the capture:** broken, failing, redirected, noindex, non-canonical and robots-blocked links, with links the crawl did not reach checked directly (up to 60 links in 30 seconds).
- **Findings and tasks** for format problems, links agents cannot use, links that could be more direct, a server error at `/llms.txt` (the one case Chrome Lighthouse fails), and a robots.txt that blocks the agents that read llms.txt on a person's behalf. Tasks close only when the llms.txt check ran again.
- **A missing llms.txt is information, not a task,** and does not lower the AI readiness score. Google Search ignores the file and says it neither helps nor harms rankings, Lighthouse marks a 404 as not applicable, and no major AI assistant documents reading it. Coding tools and assistants that are given a site can still use it, so the draft is still offered.
- **Markdown page copies (llms.txt v2):** pointers sent as `<link>` tags or as an HTTP `Link:` header are both read, and the declared copies of the strongest 10 pages are fetched to confirm they load as markdown, not as an error or an HTML page.
- **A draft built from your own capture** in `_llms-txt-draft.md`: your brand as the title, your home page description as the summary, and your live, indexable, canonical pages, strongest first, each with its own meta description, grouped by section with the rest under `## Optional`. A page that declares a markdown version is linked by that version, as the spec suggests. If you already have an llms.txt, the note lists strong pages it leaves out. The discovery checklist offers this draft as the fix instead of a generic template.
- The audit report has an llms.txt section with the structure, every note and every link result. `llms-full.txt` is recorded as a convention outside the spec, and pages that point at their llms.txt with `rel="describedby"` are counted.

### Added: run controls
For apps that run captures on a fixed plan. Each one is also a plugin setting, and every default keeps today's behaviour.
- **Capture time limit** (`--deadline SECONDS`): one limit across every network phase, from robots.txt and sitemaps through the crawl, link checks, the browser sample, snapshots, the certificate and DNS. When it runs out, nothing new is requested, the notes and map are still written, and the capture is marked partial with each phase it cut. Pages, files and links it cut are recorded as not requested or not finished, never as broken. A phase that would have too little time to finish is skipped and named, rather than run into a timeout that looks like a fault of the site.
- **Certificate check** can be turned off (`--no-tls-check`), so no TLS handshake is made.
- **Task list** can be turned off (`--no-tasks`) for teams that track fixes elsewhere. No `_tasks.md` is written, and the audit report, dashboard and Site Audit panel leave out the task list link.
- In the engine, `ROBOTS_PRODUCT_TOKEN` is now `ROBOTS_PRODUCT_NAME`. The value (`WebObs`) and the manifest key `productToken` are unchanged.

### Changed
- The manifest schema is 1.3.0 and adds `audit`, `issueCatalog`, per-page `pageChecks`, `siteIntel.browserAudit` and `siteIntel.transport`. 1.2 captures still open.
- Page notes and the manifest keep up to 40 issues per page instead of 10.
- Diagnostics list the optional packages without failing when they are missing.
- Word counts and visible text now include the heading inside `<article><header>` and leave out the `<title>` text, so counts can shift slightly on the first recapture.
- Page notes for pages rendered in the browser no longer report missing compression, which the browser path cannot observe.

### Changed: notes that mirror the page
- **Page Content keeps the page's structure.** The header, navigation, sidebar and footer are kept as labelled, collapsed callouts in their place around the main content, instead of being dropped or leaking in as bare lines. Skip links, back to top links and theme or copy buttons are left out. Rows of buttons stay links, and label and value pairs stay apart. Content hashes and word counts still cover the main content only.
- **Media and Resources** is grouped by type (images, scripts, fonts and so on) and labels each file by its alt text, link text or file name, with its size, instead of "image: image (ok)".
- **Navigation and footer links** are `[title](url)` links grouped under Header and Footer, with no code formatting. **Outgoing external links** are one bullet per link with its anchor text.
- The one long metadata line is now a small property table, which also shows a redirect when the requested address had one.
- **Full-page snapshots:** after capture, Web-Obs renders up to 25 of the most important pages once and puts a full-page screenshot in a collapsed callout under each note's title (`assets/screenshots/`). The page is photographed beyond the normal 1280 x 800 window rather than by stretching the window, so sections sized to the screen (a full-height hero) keep their size. Scrolling is instant while capturing, so smooth-scrolling sites are shot from the top with their header in place. Scroll reveals are settled, banners pinned to the bottom of the window (cookie notices, chat bubbles) are hidden, and pictures are cut at 24,000 px, with the note saying so. Settings: on or off, the page limit, and an option to also save the rendered HTML. CLI: `--no-snapshots`, `--snapshot-limit`, `--snapshot-html`.

### Changed: an honest, polite crawler
- **User agent:** every request now says `Mozilla/5.0 (compatible; WebObs/0.2.0; +https://github.com/AgriciDaniel/web-obs/blob/main/docs/CRAWLER.md)`. It no longer claims to be Chrome 135, so it matches the real Chromium client hints the browser sends. The version comes from one place, `engine/__init__.py`, which was still at 0.1.1.
- **Crawl-delay** in robots.txt is honoured in every phase: one request at a time, at least that far apart, capped at 60 seconds and reported in the capture warnings.
- **Rate limits:** on HTTP 429, or a 503 with `Retry-After`, the capture pauses for that time, retries the page once, and stops requesting new pages after three such answers. A bare 503 is retried once later.
- **New page for site owners:** [docs/CRAWLER.md](docs/CRAWLER.md) explains what WebObs sends, what never shows in web logs (the TLS handshake and DNS lookups), and how to block or slow it in robots.txt.

### Changed: a calmer interface
- **Map first:** one 47px toolbar with a short summary (pages, items needing attention, broken links, domains) replaces the stats strip. On a narrow pane it wraps onto extra rows, and the map and panels start below it. The page explorer starts closed and remembers your choice. The bottom bar shows only filters that have pages, with layer toggles in a Layers menu.
- **Readable 3D map:** at rest only home, sections, pages that need attention and the ten strongest pages are labelled, and labels never overlap. Road and Clusters fill the canvas and the camera fits every layout.
- **Site Intel** is split into Health, Files, Tech and Brand tabs. **The page inspector** has Issues, Checks, Links and Browser tabs, with problems shown first and raw tables collapsed.
- **Site audit** opens on five stat tiles, a work list and a row of charts (findings by category, pages by section, link check results, media inventory). Findings are grouped into Needs attention, Worth reviewing and Coverage gaps. Content and browser sample summaries now live here.
- Each panel keeps its caveats in one "About these numbers" section. The toolbar and the audit panel count attention items the same way.
- The plugin stylesheet now includes every style file, so the new layout also applies inside Obsidian.
- **The site's own mark at the centre:** the home node shows the site's logo on a round badge that always faces you, ringed in the brand colour. It uses what the capture already saved (the logo, then the sharpest favicon), so older captures get it without recapturing. A logo is placed on a light or dark backing so it stays visible, and the ring is adjusted to at least 3:1 contrast on both map themes. Without a usable logo the badge shows the brand's initials. The domain label stays beside it, since the logo choice is not visually checked.

### Fixed
- **A capture made with the task list off opens again.** With Task list off (`--no-tasks`), the app refused the capture as invalid, because the manifest records no task counts. That is now accepted, and malformed counts are still refused. A new check captures a local site once per engine switch and opens each result with the app's own manifest check.
- **A page cannot plant a live code block in your vault.** Code blocks keep their language only when it is a plain language such as `python` or `json`. Names that Obsidian or a vault plugin renders as live content (`mermaid`, `chartsview`, `dataviewjs`, or a name any installed plugin registers) are dropped, so the block shows as plain code. Inline code that starts with `=` or `$=` no longer runs as a Dataview query.
- **A page cannot plant a Templater command in your vault.** Templater runs `<% %>` and `<%* %>` commands wherever they appear in a new note, so page text holding one could run JavaScript when a capture lands. Every `<%` is now shown as text in prose (`&lt;%`), and carries the same invisible mark as other code after its `<` in code and properties. The site comparison note does the same.
- **Nested numbered lists stay nested.** A list inside a numbered item is indented to the item's text, so it no longer shows as a sibling of its parent. A list item that holds only code keeps its number.
- **Notes kept from an earlier capture are made safe too.** Edited, legacy and retained notes copied back during a recapture now go through the same cleaning. Existing captures are made safe on their next recapture.
- **Copying code from a captured note:** to keep notes from loading anything, code in a note carries an invisible zero-width space after `<` (before a letter, `/`, `!`, `?` or `%`) and between `!` and `[`. For exact source, copy from the page's file in `_raw/`.
- **Code shown on a page can no longer let a remote image through.** A `<pre>` that showed a Markdown fence ended the note's code block early, so HTML after it became live, and the note cleaner tracked code blocks differently from Obsidian. Code blocks now get a longer fence, the cleaner follows CommonMark, and anything that could load is made inert even in code, where it looks the same. A renderer based check covers over 3,000 generated notes.
- **Opening a captured note loads nothing from the network.** An image that was not saved stayed in the page note as a remote embed, so opening the note fetched it from the site or its CDN. Unsaved images are now plain links (`Image not saved: ...`), and saved images keep their local embed. A final pass over every note also turns HTML that a page showed as text (in titles and body text) into text, and Markdown or wikilink embeds written as page text into links. The site comparison note does the same for site text.
- **robots.txt rules are ranked the way Google and RFC 9309 rank them.** The longest rule as written wins, `*` and `$` included, so `Disallow: /*.htm` beats `Allow: /page` for `/page.htm`, as in Google's own example. Before, the crawler could fetch such URLs. `User-agent: GPTBot/1.1` and `GPTBot*` now mean GPTBot, and path parameters such as `;jsessionid=1` are matched as part of the path. A user-agent value that is not a valid name (`80legs`, `360Spider`, `*bot`) still starts its own group, one that applies to no crawler, so its rules never join the group above it. Crawl-delay is read by the same groups, so `User-agent: WebObs/1.0` with `Crawl-delay: 10` now slows WebObs down.
- **An unreadable robots.txt is no data.** When robots.txt could not be read (a server error, rate limiting, a timeout or an oversized file), the dashboard said all AI crawlers were allowed. It now says AI crawler access is unknown, and the AI readiness score shows no data instead of a pass. The site drawer and the site comparison show "No data" instead of "0 of 16" and "Blocked: None".
- **Googlebot's 2 MB HTML cutoff.** Pages whose HTML is over 2 MB before compression are flagged, because Googlebot reads only the first 2 MB for Google Search. The check was at 3 MB and described as a speed issue. Older captures keep their HTML over 3 MB finding, with the corrected explanation.
- **Chinese, Japanese, Thai and other languages written without spaces** are no longer reported as thin content, short titles or descriptions missing from the body on nearly every page. For these pages no word count is shown: the page panel and inspector say "Not measured", the page note says "Not measured for this language" and records `words_measured: false` instead of `word_count`, and the Thin Pages view and the site comparison leave them out. The duplicate and dead-end checks, which need a minimum word count, do not consider these pages yet.
- **Spell check skips pages that do not declare their language,** instead of checking them against the English dictionary.
- **Wording that follows Google's documentation:** little body text is no longer framed as a ranking rule (Google has no minimum word count), several H1s and skipped heading levels are described as a title and accessibility matter, a meta refresh is a review item that Google follows, invalid JSON-LD costs rich results, not indexing, a missing title explains how Google builds one, and non-ASCII URLs are fine in the audience's language when links encode them.
- **Map labels show on a cold start.** On a slow first render the resting labels were worked out before the pages had loaded, and stayed empty until a filter changed.
- **New snapshots and notes now show in Obsidian right after a capture.** A capture replaces the site folder in one move, and Obsidian kept its old file list for a folder it already knew, so new files (such as snapshots) said "could not be found" until a reload. The plugin now has Obsidian re-index the site folder and re-attach its watchers after every capture, and asks for a reload only if that is not possible.
- Page Audit screenshots are embedded with their full vault path.
- **Inline SVG logos are saved as real, scalable logos.** The capture took the first SVG in the header, which could be a theme toggle or menu icon, and the HTML parser lowercased case-sensitive SVG names such as `viewBox` and `linearGradient`, so saved logos rendered unscaled or lost gradients. An inline SVG now needs a logo signal (inside the link to the homepage, or named logo or brand, never inside a button), and SVG names keep their case.
- A robots.txt that starts with a byte order mark had its first group misread. It is now decoded correctly.
- A page whose HTML holds a malformed URL (such as `https://[bad`) no longer ends the whole capture. It is saved as unavailable with the reason. If every page fails to parse, the capture stops and the previous one stays in place.
- The site audit runs inside its own guard. If it fails, notes and the map are still saved and the capture says why.

## 0.1.1 - 2026-11-03

Accuracy fixes from a full capture of a live trailing-slash WordPress site. Behaviour changes are listed so you can tell why numbers differ from a 0.1.0 capture.

### Fixed
- **False redirects on trailing-slash sites.** Pages are now fetched and stored at the address the site publishes, with its trailing slash. Before, `/about/` was requested as `/about`, the site redirected back, and nearly every page was marked as a redirect (68 of 69 on the test site, 61 redirects in sitemap hygiene). A URL is reported as a redirect only when the published URL itself redirects, including a sitemap URL whose destination was also crawled.
- **Pages missing from the sitemap are counted again.** A page used to carry one status, so a redirect hid "unlisted" and `unlistedPages` read 0. Each page now also carries independent `flags` (`redirect`, `orphan`, `unlisted`, `noindex`), and the orphan and unlisted counts come from them. The existing `health` value is unchanged and still drives colours.
- **Sitemaps are counted once.** Several paths that redirect to one sitemap (for example `/sitemap.xml` to `/sitemap_index.xml`) no longer inflate `sitemapsFound` or `undeclaredSitemaps`.

### Changed
- **Response time is the final request only.** `responseTimeMs` now measures the final request, from connection to the last body byte, and no longer includes redirect hops. New fields: `ttfbMs`, `fetchDurationMs` (all hops) and `redirectHops`. New stats: `medianResponseTimeMs` and `avgFetchDurationMs`. The Site Intel label is "Avg page request time". Pages rendered in a browser still report the whole render time.
- **Alt text.** Only a missing `alt` attribute counts as `images-missing-alt`. An empty `alt` is valid for decorative images and is counted separately as `imagesEmptyAlt`. An image counts as decorative when it or an ancestor has `aria-hidden="true"`, `role="presentation"` or `role="none"`.
- **Heading levels.** `heading-level-skip` is judged inside the main content when the page has one. Skips in the header, navigation, footer and sidebar are counted separately as `templateHeadingSkips`.
- **Capture status.** `captureStatus` is `partial` only when something was not collected (limits, budgets, blocked or failed fetches). A page or resource that answers 404 or 410 is a finding, listed in the new `captureFindings` and shown in Site Audit, and no longer makes the capture partial.
- **Canonical checks** treat a canonical that differs from the page only by its trailing slash as the same page.

### Added
- `internal-link-form-mismatch` check: an internal link written in a different form than the published address (for example `/contact` on a site that publishes `/contact/`) is listed on the page that contains it, with the address it should use. These links usually redirect.
- Regression test `scripts/verify-trailing-slash.py`, part of `npm run verify`.

### Upgrade note
Notes and map nodes from 0.1.1 use the published address, so a site first captured with 0.1.0 may show its URLs as changed on the first recapture.

## 0.1.0 - 2026-11-03

First release.

### Capture and map
- Capture a website into your vault: sitemap first, clean Markdown notes, local images, internal and external links.
- Interactive 3D Site Globe with Globe, Road and Clusters views, a page explorer, and a Site audit view.
- Safe recapture: edited notes are preserved and fresh versions are saved for review.

### Site checks and tooling
- The capture engine is packed inside `main.js` and unpacked on first start, so installing only `main.js`, `manifest.json` and `styles.css` works. A missing or edited engine file is restored on the next start.
- `npm run release` builds a local zip (`release/web-obs-0.1.0.zip`) with a SHA-256 file. It never publishes.
- Site health card and Discovery files panel in Site Intel, with copyable starter files.
- Validation for llms.txt (llmstxt.org) and security.txt (RFC 9116, including expiry).
- Probes for api-catalog (RFC 9727), humans.txt and manifest.webmanifest, with up to three same-site redirects.
- Per-origin robots.txt policy using RFC 9309 and the `WebObs` product token.
- Sitemap hygiene: broken, redirected and noindex URLs, undeclared sitemaps, redirect chains, lastmod mismatches and non-reciprocal hreflang.
- Site checks: HTTP to HTTPS, www and non-www, and soft 404 responses.
- Security headers compared across sampled pages, plus an HSTS max-age note.
- Performance row from server signals (response time, compression, HTML size).
- IndexNow listed as not detectable.
- More AI bot tokens, including user-triggered fetchers.
- Diagnostics command and modal, with a Run diagnostics button in settings.
- Readable error messages for engine failures.
- Failure-path tests: robots.txt 500, malformed robots and sitemaps, oversized sitemaps, resets, missing vault, cancellation.

### Performance and polish
- 3D map renders on demand. A settled map stops drawing and stops reading label sizes, hover tracking no longer queries the DOM every frame, and the orientation gizmo updates only when the camera moves. Measured in software WebGL on the standalone app: callback time 15 ms to 9 ms with Light Flow on, and a settled map with Light Flow off went from 6,000 draw calls per second to none.
- Page-level checks: nofollow, missing viewport, invalid JSON-LD and missing self hreflang.
- Verification and design reports moved to `docs/`.
