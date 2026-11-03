# Changelog

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
