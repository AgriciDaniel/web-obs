# Shared styles modules (copies)

`color.mjs`, `styles.mjs` and `styles-hash.mjs` are exact copies of `apps/viewer/brand/` in the report app (v0.1.7, tag `v0.1.7`, commit `65eccc7c902f`; the report app repository is private). The plugin keeps its own copy, like the contract, so it has no build step against the report app. `scripts/verify-report-look.mjs` checks each file against the sha256 of the report app's file, so a copy that drifts fails the check. Do not edit these files here: change them in the report app and copy them again.
