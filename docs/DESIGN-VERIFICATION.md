# Obsidian design follow-up

Applied and verified on 2026-11-02. The installed Web-Obs plugin now uses the visual direction supplied at http://127.0.0.1:8765/ and https://obsidian.md/.

The reference pages were visually inspected and their computed colours recorded. Their shared dark base is #0f0f0f, with charcoal surfaces around #1e1e1e, warm white text and #a882ff violet accents. Web-Obs uses those colours locally, with a #7c3aed primary action colour. The light theme uses white and neutral grey surfaces with the same violet direction.

## Changes

- Neutral backgrounds replace the former navy surfaces and radial page background.
- Borders, shadows, corner radii and active tabs are quieter.
- Interface typography follows Obsidian's interface font when available, with local system fallbacks.
- The map centre, wireframe, pulse tint, links, focus rings and audit section bars use violet accents.
- Green, amber and rose remain distinct for successful, review and error observations.
- The native audit close button explicitly resets host padding so its icon retains its intended size.
- Narrow toolbars scroll their own controls, preventing keyboard focus from shifting the whole page sideways.

## Current verification

| Check | Result |
| --- | --- |
| TypeScript and plugin build | Passed |
| Audit browser interactions and responsive layouts | 6 passed |
| Map discovery, hover neighbourhood and reduced motion | 12 passed |
| Continuation success, cancellation, failure and narrow layout | 7 passed |
| Installed audit view inside isolated Obsidian | 5 passed |
| Dark and light body/link contrast against panel surface | At least 4.5:1 for sampled text tokens |
| Packaged, installed and native test artifact hashes | Identical |
| Engine manifest | Byte-for-byte unchanged |
| Existing captured files | All 1,013 original file hashes unchanged |

Browser layout checks include 1440px, 1280px, 900px and 390px viewports. Chromium and native Obsidian used software rendering. Text contrast checks are limited to the sampled tokens, not a complete accessibility certification. Backend capture logic was unchanged; the earlier functional verification remains documented in VERIFICATION.md.

## Evidence

The local evidence folder is:

`~/.cache/web-obs-obsidian-design-20261102T161519Z`

It contains reference screenshots, reference-styles.json, dark and light audit/map/inspector screenshots, responsive UI results, native screenshots, sampled contrast results, before-edit backups and exact artifact hashes.

Open `audit-dark.png`, `audit-light.png`, `globe-dark.png`, or `native-audit-final/audit-desktop.png` to inspect the result. The same plugin is installed in this vault. Reload Obsidian to load the updated bundle.
