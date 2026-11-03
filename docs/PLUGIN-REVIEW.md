# Reviewed Obsidian audit plugins

Reviewed on 2026-11-02 after the capture upgrade. The supplied community pages were unavailable through the web reader. Public repositories, manifests, licenses, source files, a dependency lock and a compiled bundle were inspected instead. Raw records are retained in the capture evidence directory under `plugin-research/sources.json`.

Recommendation: keep Web-Obs as the capture runtime and add these projects to the reference stack. Installing both would add overlapping crawlers and different scoring assumptions. No third-party plugin was installed, enabled or copied into the runtime in this review.

## Safi Site Audit

Reviewed plugin 0.6.1 at `1731900d6ee293c8615ac80571c44f56a4e117d0`. Its lock pins scanner 1.0.2; the reviewed scanner repository is version 1.0.2 at `f1b2d7dc12386853aac2ab7f53f589e4a1290cc2`.

Useful features are category breakdowns, actionable findings, per-site history and separate Markdown, JSON and standalone HTML reports. Its README advertises 94 rules across 15 categories; the rule index loads 15 category modules. Those rules were read selectively, not executed independently. [README](https://github.com/Abdulkader-Safi/obsidian-safi-site-audit-plugins/blob/1731900d6ee293c8615ac80571c44f56a4e117d0/README.md), [rule index](https://github.com/Abdulkader-Safi/Safi-Studio-Scanner/blob/f1b2d7dc12386853aac2ab7f53f589e4a1290cc2/src/rules/index.ts).

Local HTTP audits do not inherently require a key. An optional PSI key is forwarded to a provider that calls Google's PageSpeed endpoint. That provider is outside our runtime scope. The wrapper does not support its local Playwright provider inside Obsidian. [Runner](https://github.com/Abdulkader-Safi/obsidian-safi-site-audit-plugins/blob/1731900d6ee293c8615ac80571c44f56a4e117d0/src/audit-runner.ts), [PSI provider](https://github.com/Abdulkader-Safi/Safi-Studio-Scanner/blob/f1b2d7dc12386853aac2ab7f53f589e4a1290cc2/src/providers/psi.ts).

Its transport temporarily replaces `window.fetch` with a `requestUrl` shim. Redirects auto-follow, so chain counts are unavailable. Abort handling races a promise while the underlying request can finish later. Retain our owned workers and per-hop checks instead of importing this transport. [Fetch shim](https://github.com/Abdulkader-Safi/obsidian-safi-site-audit-plugins/blob/1731900d6ee293c8615ac80571c44f56a4e117d0/src/fetch-shim.ts).

The useful native follow-ups are a grouped issue inbox, a visible history browser and a portable HTML report. Web-Obs already has retained history, Markdown/JSON, Bases, Canvas, receipts and graph exploration; adding another crawler is unnecessary.

## SEOWebChecker SEO Audit

Reviewed plugin 1.0.1 at `7bc8d801c10fd2755541dcd40a076d8aa506529d`.

The reviewed source analyzes Markdown locally and debounces editor changes by 600 ms. Its package has development dependencies and no hosted audit SDK runtime dependency. The live URL action requests the entered website through Obsidian `requestUrl`; the reviewed source does not call a hosted SEOWebChecker audit endpoint. This was source inspection, not an installed-plugin runtime test. [Main module](https://github.com/jaiganesh6999/obsidian-seowebchecker-audit/blob/7bc8d801c10fd2755541dcd40a076d8aa506529d/src/main.ts), [live view](https://github.com/jaiganesh6999/obsidian-seowebchecker-audit/blob/7bc8d801c10fd2755541dcd40a076d8aa506529d/src/view.ts), [package](https://github.com/jaiganesh6999/obsidian-seowebchecker-audit/blob/7bc8d801c10fd2755541dcd40a076d8aa506529d/package.json).

Its useful difference is draft editing. A future native mode should keep edited-note assessments separate from immutable capture evidence and inspect the intended article body. Generated capture notes also contain report headings and resource lists, which can distort note-level metrics.

Do not import its composite score as an SEO outcome. It deducts points for fixed title, description, word-count, readability and keyword-density thresholds. These are heuristics. English readability is not language-independent, and its line-based frontmatter parser is not full YAML. Heading jumps, alt checks and generic anchors already exist in Web-Obs. [Analyzer](https://github.com/jaiganesh6999/obsidian-seowebchecker-audit/blob/7bc8d801c10fd2755541dcd40a076d8aa506529d/src/analyzer.ts).

## Stack decision

| Capability | Decision |
| --- | --- |
| Capture, resources, robots, links and graph | Keep Web-Obs |
| Safi rule categories and issue presentation | Native saved-evidence audit panel with charts and grouped findings; no Safi scanner bundled |
| Safi PSI provider | Exclude from the runtime |
| Safi global fetch shim | Do not adopt |
| SEOWebChecker local draft diagnostics | Optional drafting reference, separate from site evidence |
| Fixed density targets and composite grades | Do not adopt as ranking or health claims |
| Portable HTML report and visible history browser | Useful future additions, not implemented in this capture pass |

Both repositories contain MIT license texts. Later substantial code reuse must retain the applicable notices. This pass copied no third-party runtime code. [Safi license](https://github.com/Abdulkader-Safi/obsidian-safi-site-audit-plugins/blob/1731900d6ee293c8615ac80571c44f56a4e117d0/LICENSE), [SEOWebChecker license](https://github.com/jaiganesh6999/obsidian-seowebchecker-audit/blob/7bc8d801c10fd2755541dcd40a076d8aa506529d/LICENSE).

The tradeoff is maintaining one capture implementation and adapting useful local features, instead of enabling several plugins with overlapping network and scoring behavior. This review is not a security certification of either plugin.

## Native audit presentation added

The 2026-11-02 follow-up adds the Web-Obs **Site audit** view: destination status and media distribution charts, section bars, searchable findings, affected-page inspection, explicit sampling and unassessed areas. It uses existing capture evidence and makes no additional request when opened. The Safi 94-rule scanner, its scores, history sidebar and standalone HTML export are not included. Web-Obs capture history remains available on disk.

The current official listing was rechecked on 2026-11-02 and still describes 94 rules in 15 categories and optional PageSpeed Insights enrichment. [Official Safi listing](https://community.obsidian.md/plugins/safi-site-audit). No third-party runtime code was copied for this view.
