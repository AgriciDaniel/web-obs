# Native integration acceptance

Tested on 2026-11-09 using the Obsidian Plugin Creator review and acceptance workflow, plus Obsidian Control Center and its official CLI transport. This checkpoint covers the source update to plugin version 0.2.2 before a tagged release.

## Artifact

`main.js` SHA-256: `984cdcfd07caf2e4041889d381f0efc9c3b8dd8e1ecf8d02cee0cff9f47fdef1`

The build and installed vault copy match. The complete engine source, build and installed file hashes also match. The separate client report application was tested from source commit `dd17fcd50754549cd295c0ff47fdc3aec846d4e9` without source modifications.

## Observed results

| Evidence | Result | Scope |
| --- | --- | --- |
| Plugin Creator static review | Passed its implemented signals | Source scan; does not replace runtime tests or lint |
| Full Web-Obs regression gate | Passed | `npm run verify`, local crawler fixtures, software WebGL tests, TypeScript and vault parity |
| Dependency audit | 0 known advisories | `npm audit`, including development dependencies after targeted overrides; checked with a fresh `npm ci` |
| Source lint | 0 errors, 0 warnings | `npm run lint`, pinned official recommended rules with documented browser/Node scopes and product terminology |
| Native settings search | 4 checks passed | Actual settings search result, persisted toggle, byte-for-byte restoration and empty secret inputs |
| Native comparison | 3 checks passed | Actual dialog, validated manifests, saved Markdown table and editor opening |
| Lifecycle regressions | 38 passed | Mocked process and host APIs, including cancellation after closing the owning view |
| Native integration | 13 stages passed | Isolated Linux Flatpak Obsidian 1.15.0 with installer 1.14.5, actual installed plugin, synthetic sites and loopback report servers |
| Native capture | 9 checks passed | Actual Python child, robots handling, queues, link results, map, Site Intel, Markdown note opening and generated Bases |
| Built client viewer | 6 checks passed | Native plugin export, all 12 guided steps, refresh continuity, narrow layout, local feedback outbox, unavailable-link state and no external browser requests |
| Separate report repository | Build and full tests passed | Local synthetic fixtures with isolated temporary and Git configuration |
| Normal vault reload | Passed | Actual Obsidian 1.15.0, updated Publish and Archive controls and scrolling styles, existing Markdown files preserved, settings and editor buffers preserved |

The native integration stages cover local export, actual HTTP publishing and viewer retrieval, stored and environment credential priority, rejected and missing credentials, map modes, translucent appearance, archive propagation across two panes, restoration, repeated view close/reopen, workspace restoration and native settings with empty password inputs. A separate byte comparison confirmed all 22 files in the restored synthetic capture match its preimage.

The normal-vault check did not create or upload a real client report or archive a real capture. Live publishing remains unconfigured.

## Corrections from the follow-up

- A local logo path could enter client JSON. Projection now excludes it, with a retained failing reproduction and a passing regression.
- Explicit environment credentials still caused a secret prompt. Available environment credentials now precede that prompt.
- Archiving left stale site state in a second open pane. The host now broadcasts the archive and refreshed site list.
- Confirmation controls could fall outside a short split pane. The form area scrolls and inputs fit its width.
- A cancelled capture could outlive its closed pane. A shared shutdown tracker blocks Archive until the child exits.
- Imported report validation used unchecked types. Its schema and value checks now have explicit TypeScript types, with report export, ingestion and built viewer compatibility verified.

## Lint and compatibility follow-up

All 137 source error findings in the previous candidate are resolved. The same temporary official default configuration now reports zero errors and 41 warnings. The checked-in `eslint.config.mjs` reports zero errors and zero warnings and runs inside `npm run verify`. It keeps the recommended type-safety and API checks enabled. Its explicit scopes preserve standard DOM creation in the two standalone-browser renderer modules, streaming browser fetch in the standalone host, cross-runtime layout timers and the fixture-readable developer override. Product names, acronyms and environment variable names retain their exact casing. Raw default and repository-configured results are both retained. Targeted development dependency overrides fix the reported minimatch and moment advisories without changing the plugin bundle; a fresh `npm ci`, lint, build and local capture-host checks verify the resulting lockfile. `npm audit` reports zero known advisories across the full installed dependency graph.

Comparison inputs now pass manifest validation, unavailable measurements stay unavailable instead of becoming zero, local capture requests narrow unknown JSON values, and asynchronous command and child-exit callbacks handle failures. Plugin paths respect custom vault configuration directories. View activation uses an API version guard for Obsidian before 1.7.2. Settings are searchable on modern Obsidian while retaining the imperative screen for the declared 1.5 minimum. Native acceptance ran on 1.15.0; the older-version fallback is source-checked, without an installed 1.5 runtime test.

The normal-vault reload verified the exact updated bundle and retained the existing captured Markdown files, plugin settings and open editor buffers. It opened and closed an unapproved Publish confirmation to inspect scrolling without creating a report.

## Remaining limits

Production hosting, Cloudflare authentication, real credentials, public release approval and human review of client-specific findings remain outside this local acceptance. SSH has mocked process coverage; a live SSH server was not exercised. No physical GPU frame-rate or heap-retention claim is made. Mobile is outside this desktop-only plugin's advertised scope. Optional email DNS and spell-check switches could not be exercised in the dependency-limited local switch fixture.

Raw logs, screenshots, source and artifact hashes, preimages and negative runs are retained privately by the maintainer. They are excluded from source control. Automated checks are available in `scripts/`; native checks require an explicitly disposable Obsidian vault and a separate local Obsidian Control Center checkout. No personal vault files or private test evidence are included in this source update.
