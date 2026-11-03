# Map discovery verification

Verified 2026-11-02 after the coordinated capture pipeline checkpoint.

Added Explore this map, manual highlights with camera focus, Surprise me with unvisited-page preference, real captured link navigation, a session exploration count, explicit Inspect, arrow-key navigation and Escape focus restoration. Discovery respects visible filters and search results. It supports Globe, Road and Clusters, compact panes and reduced motion.

The UI never writes capture data. All 1,289 existing capture files retained identical hashes. The engine manifest matches the earlier peer checkpoint. The App change is the approved single callback to close the existing details panels when discovery starts.

Validation passed:

- npm run build: TypeScript, browser bundle and Obsidian plugin package.
- npm run verify: existing complete local regression gate, including local HTTP fixtures, native-host mocks, Flatpak execution and package parity.
- node scripts/verify-map-discovery.mjs: 6 deterministic data cases.
- python3 scripts/verify-map-discovery-ui.py --evidence <directory>: 12 actual Chromium checks using the bundled offline sample at 1440, 1280, 900 and 390 pixel widths.
- python3 scripts/verify-map-discovery-native.py --vault <isolated-vault> --evidence <directory>: 8 actual isolated Obsidian checks using a copy of the retained agrici capture with 50 pages.
- main.js, styles.css, manifest.json and engine-manifest.json match between the package, workspace installation and isolated native installation.

Native acceptance used software WebGL. No FPS claim, physical GPU benchmark, mobile-device test or human visual approval is implied. No new public website capture ran for this UI pass. The capture checkpoint and its evidence remain separate in VERIFICATION.md and PLUGIN-REVIEW.md.

The local plugin is installed in .obsidian/plugins/web-obs. Reopen the plugin view or reload Obsidian to load the update in an already running session.

Evidence: ~/.cache/web-obs-discovery-20261102T113509Z

Final main.js SHA-256: 8777b4e1246423d0c744c5b9c1eb8823ac816e842a89b9a8abb1d99e5476590f
