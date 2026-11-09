# Web-Obs verified implementation checkpoint

The [client report integration acceptance](NATIVE-INTEGRATION-ACCEPTANCE.md) records the 2026-11-09 artifact, full regression, lint and native evidence. This document retains its earlier dated checkpoint.

The later [Obsidian design follow-up](DESIGN-VERIFICATION.md) records the current visual theme, browser/native checks and updated artifact hashes.

Verified on 2026-11-02. The installed Web-Obs plugin includes capture, Globe/Road/Clusters, map discovery, Site Intel and the native Site audit view.

The runtime uses local Python 3.14 or newer, local browser scripts and ordinary website HTTP requests. This machine and the selected engine environment report Python 3.14.8. No AI model, API key, hosted audit provider or PageSpeed Insights integration is used.

## Verification

The default `npm run verify` gate passed 208 behavioral checks, the standalone host flow, a six-page end-to-end fixture, bundled engine execution inside Obsidian Flatpak, TypeScript compilation and source/package/installed-engine parity. The behavioral checks include:

| Area | Cases | Evidence |
| --- | ---: | --- |
| Native lifecycle and Python capabilities | 33 | Mocked Obsidian interfaces and processes |
| Browser discovery | 7 | Filesystem fixtures |
| No-API browser policy | 6 | Local HTTP and actual Chromium |
| Robots, URL safety and direct links | 35 | Local HTTP and negative cases |
| Receipts and evidence exports | 22 | Retained bytes and HTTP fixtures |
| Recapture and member-file preservation | 13 | Temporary vaults and injected failures |
| Integrated capture | 7 | Local HTTP and actual outputs |
| Resource classification | 8 | MIME, captions, SVG and download limits |
| Worker and browser boundaries | 25 | Processes, TLS, Chromium, TCP and UDP |
| Parallel pipeline | 13 | Local HTTP, deterministic outputs and budget cases |
| Complete Canvas export | 5 | Synthetic inventories up to 250 pages |
| Link continuation and provenance | 9 | Local HTTP, source changes and rollback |
| Manifest resource validation | 10 | Malformed and retained data |
| Map discovery data | 6 | Deterministic graph cases |
| Site audit data | 9 | Captured, sparse and synthetic observations |

Separate actual Obsidian acceptance passed 21 checks: 12 capture/media/notes/Bases checks, five audit-view checks and four continuation checks. The tested native bundle hashes match this vault and `dist-plugin`.

Actual standalone Chromium acceptance passed another 25 checks: 12 map/discovery/hover cases, seven continuation success/cancel/failure cases and six audit view cases. Audit and discovery layouts were checked at 1440, 1280, 900 and 390 pixels. Software WebGL was used. This is not a physical RTX benchmark or human visual approval.

## Live agricidaniel.com result

The reviewed snapshot is installed under `sites/agricidaniel.com/`. Its previous capture is retained in `.web-obs/history/`.

| Observation | Result |
| --- | --- |
| HTML pages | 50 from 50 sitemap URLs |
| Canvas pages | 50, exactly matching internal graph nodes |
| URL resources | 554 |
| Local images including inline SVGs | 208 |
| Saved captions | 4 |
| Audio / video references | 5 / 14, outside the page graph |
| Destination targets attempted | 814 / 814 |
| Successful responses | 796 |
| Inconclusive responses | 18 |
| Confirmed HTTP 404/410 targets | 0 |
| Collection warnings | 0 |
| Page heuristic flags | One title-length flag |

The initial preferred-image capture took 50.19 seconds. Link continuation ran separately in bounded sessions. This is not a controlled comparison with the older all-variant capture. Preferred mode retained all 554 URL resources and omitted 279 responsive variants from local downloads intentionally, while preserving the page image embeds.

An integrity check passed for 397 generated inventory files, 181 locally saved URL resources, 212 generated media files including inline SVGs and captions, 50 retained HTML receipts, 259 local image embed references and all graph notes. The 20 transformed SVG resources now have distinct source and stored hashes. No integrity checks were left unperformed by that validator.

The live test exposed HEAD-only false missing responses from Google Help. HEAD 404/410 results now require streamed GET confirmation; fallback bodies are not consumed. All nine observed false alarms were corrected. Inconclusive responses remain unknown. All targets being attempted does not make coverage conclusive: `coverageComplete` remains false while those 18 outcomes are unresolved.

## Implemented improvements

- Canvas exports include every internal page and eligible relationship. The saved agricidaniel.com Canvas was repaired from 47 to 50 pages. The claude-seo.md Canvas was repaired from 60 to 63 after its old bytes were proven identical to the original generated output. Both retain history and original page capture timestamps.
- Asset count, aggregate-byte and per-file omissions now warn and mark the collection partial. Intentional preferred-mode omissions remain separate.
- Resource labels, optional text, metrics and displayed evidence fields are validated before reaching React.
- Site Intel and Site audit can continue unchecked targets and legacy HEAD-only missing confirmations without recrawling pages or downloading media bodies. Results, reports, update times and session provenance are retained separately from page collection time.
- Preferred images are the default; All image variants remains available in settings and CLI. Audio/video bodies remain references and small captions remain separate files.
- Technology detection states its eight-page sample out of 50 captured pages, selected source URLs and homepage-only security-header scope.
- Captures retain configuration, engine source hashes and Python/package versions. Source changes during collection abort before promotion. Edited member assets preserve their actual installed hash and a generated proposal.
- Native audit charts show destination statuses, page sections and media states. Searchable categories lead to recorded pages, source pages, notes and URLs. The view makes no new scan when opened.

## Scope of the Safi comparison

The native panel adapts audit presentation ideas. It does not bundle Safi's scanner, its full 94-rule set, composite score, audit-history sidebar or standalone HTML export. See [the plugin review](PLUGIN-REVIEW.md). Core Web Vitals, full accessibility, E-E-A-T, cookie consent and legal compliance remain explicitly unassessed. Header presence checks cover one homepage response and do not establish site-wide security.

History and proposals remain available on disk. This checkpoint is functional verification, not a formal clean-session security certification or an assurance that every website can be fully captured. JavaScript content requiring blocked background data can remain incomplete.

## Reproduce

```bash
npm run verify
engine/.venv/bin/python3 scripts/verify-capture-integrity.py --vault . --site agricidaniel.com --evidence /tmp/web-obs-integrity.json
```

Browser and native acceptance scripts are separate from the default gate. Native scripts require an explicitly isolated test vault and CDP port; they refuse an unexpected vault.
