# Changelog

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
