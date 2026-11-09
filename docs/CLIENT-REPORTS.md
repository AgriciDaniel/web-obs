# Client reports and capture archives

Open a captured site's **Site Audit** in Obsidian desktop to find **Publish** and **Archive**. These controls are unavailable for the preview site and the standalone browser app.

## Publish

Review the audit findings, press Publish, enter the approver's name, and approve the report. The report includes page titles, public URLs, the site map, audit findings and the approver's name. It excludes vault note paths, raw page text, resource inventories and agency notes. Review the site and findings before sharing them.

In **Settings, Web-Obs, Client reports**, choose a destination:

- **Client reports folder:** a full path for a local JSON export under a random name. This alone does not create a private server link.
- **Publish target:** your report server's HTTPS base address, such as `https://audit.example.com`. Web-Obs appends `/ingest/v1/reports`. The server must implement the `webobs.client-report` v1 contract and return a link, link ID and expiry. The viewer and ingestion service are separate software; the plugin does not deploy them.
- Advanced targets also accept `host:/absolute/folder` over SSH or a full local folder path. These write `reports/` and `registry/` in the server's layout. Set **Report viewer address** to receive a link for these targets. SSH uses your existing configuration and agent, requires a known host key, and cannot prompt for a password.

A publish target takes precedence over the client reports folder. When neither is configured, Publish opens a destination dialog. Remembering a destination stores only its address or folder path.

The **Publish secret** authorizes HTTPS ingestion. Optional **Cloudflare Access ID** and **Cloudflare Access secret** supply a service token where the server requires it. Values entered in settings go to Obsidian's secret storage, when supported, and are excluded from plugin settings. The ingest secret can also be entered for the session through a prompt. Older Obsidian versions without secret storage need the explicit environment option for Cloudflare credentials.

**Also read secrets from environment variables** is off by default. When enabled, it permits `WEBOBS_INGEST_SECRET`, `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` as fallbacks. Do not put credentials in a URL or a vault note.

Stored credentials take priority. An available environment ingest secret, when explicitly enabled, is used before asking for a session secret.

HTTPS requests have a timeout and do not follow redirects. Plain HTTP is accepted only for localhost or `127.0.0.1` development targets. Push publishing requests a 72-hour link. Copy the returned link before closing the dialog. Anyone holding a valid private link can read its report until it expires or is revoked on the report server. Archiving a local capture does not revoke a published link.

## A report with a look

A client report can carry an optional **look**: a flat list of checked style slots under `styles` (the accent, a second color, link, text and muted colors, a card color with its own card text, two bundled font names, a heading case, an agency name and a footer line). There is no slot for the page background or the 3D map, so a look cannot change them. A report without `styles` is exactly as before, and the viewer shows its built-in look.

The exporter takes the look as an option and checks it again with the shared function in `src/report/styles/`, which is an exact copy of the report app's code (a test compares each file with the report app's sha256, so a copy that drifts fails). A look that is not valid stops the export with a plain message. The report's integrity seal covers the report without its `styles`.

A report that carries a look is sent to a publish target as **one request with exactly two named parts**, `styles_<hash>` and `data_<hash>`. Both names hold the same hash of the look, so the server can pair them, and the data part is the report without its `styles`. A report without a look is sent as it always was. The look is checked before anything is sent, so a bad one never leaves the computer.

This needs report app **0.1.4 or later** on the server and the ingest. An older server does not know the two-part request and answers that it is not a client report; for a report with a look the plugin turns that into a plain message (update the server and the ingest to 0.1.4, or publish with the default look). A folder target stores the report with its look inside it, and the server checks the look again when it serves the report.

## Archive and restore

Archive first lists the exact folders and file counts. Type the saved site's ID to confirm. Finish captures or wait for cancellation to complete before archiving. Closing a capture pane does not bypass that wait. A capture awaiting recovery also blocks Archive. Do not run a separate command-line capture against the same vault during an archive.

The plugin moves the site's active capture, history, preserved proposals and any matching site folders inside staged transactions to a unique folder beneath `.web-obs/trash/`. Other sites are preserved. Directory links are refused, and links inside capture files are moved without following them.

All open Web-Obs panes refresh after an archive, including panes displaying that site. Confirmation forms can scroll within short panes.

Each archive contains **REMOVED.txt** with the original destinations. To restore, close Web-Obs views, make sure no new capture occupies those destinations, and move each listed folder back to its original path. Reopen the view to refresh its site list. Nothing in the archive is automatically deleted.

## Verification and origin

The Publish and Archive integration comes from gcollins808's supplied changes archive, SHA-256 `3d31d21ca7802fc8a6669c1f2884171f38dd2f60cff0442043374400d326e3d5`, with local archive and response-validation fixes. The separate report server was inspected at commit `dd17fcd50754549cd295c0ff47fdc3aec846d4e9`. Its private viewer source and deployment configuration are not included in this plugin.

`npm run verify` includes export privacy, archive recovery, publish target, secret-source and renderer checks. The optional cross-repository test uses synthetic data and loopback servers only:

```bash
REPORT_SERVER_DIR=/path/to/web-obs-client-report/apps/server node scripts/verify-export-ingest.mjs
```

It checks that a plugin-generated report is accepted by ingestion and served by the viewer server, and that a report with a look is sent as the two-part request (`styles_<hash>` and `data_<hash>`), accepted, and served with its look. Without that separate source checkout, the test reports an explicit skip. It does not verify a production host, Cloudflare configuration, real credentials, native GPU performance or human approval of report wording.

The dated [native integration acceptance record](NATIVE-INTEGRATION-ACCEPTANCE.md) covers the follow-up native application, capture, report viewer and regression checks.
