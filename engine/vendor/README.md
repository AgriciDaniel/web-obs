# Vendored files

## axe-core 4.14.0

- `axe.min.js` comes from the npm package `axe-core@4.14.0` by Deque Systems, published 2026-10-05.
- License: Mozilla Public License 2.0, see `axe-core-LICENSE.txt`. Third-party notices are in `axe-core-LICENSE-3RD-PARTY.txt`.
- SHA-256 of the published `axe.min.js`: `20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878`.
- One change: the two literal year-range dash characters inside the core-js copyright string were rewritten as the equivalent JavaScript unicode escape sequence, so the file passes the project's character hygiene check. The program behaves identically.
- Web-Obs injects this file into sampled pages during the optional browser audit (`engine/browser_audit.py`). It runs locally in the capture browser and sends nothing anywhere.
