# Troubleshooting

Start with **Web-Obs: Run diagnostics** in the command palette. It runs the checks below and shows a fix for each problem. Web-Obs never installs packages for you.

## Capture will not start

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Python was not found at ..." | The configured executable does not exist | Set the correct path in Web-Obs settings. A virtual environment's `bin/python3` works best. |
| "Python 3.14+ with requests, beautifulsoup4 and lxml is required" | Old Python or missing packages | Create a 3.14+ environment and run `pip install requests beautifulsoup4 lxml` in it. |
| "The Python environment is missing ..." | A package is missing at run time | Run `pip install requests beautifulsoup4 lxml` in the selected environment. |
| "Web-Obs requires a local desktop vault" | The vault is not a local folder | Open the vault with Obsidian desktop. |
| "engine/crawl_site.py not found" | The engine could not be unpacked on start | Restart Obsidian. If a notice says it could not unpack, check that the plugin folder is writable. |

## Single page apps capture as empty shells

Rendering needs Playwright and Chromium. In **Auto** mode Web-Obs falls back to plain HTTP when they are missing. Run `playwright install chromium` in the same environment, then check settings for **JavaScript / SPA rendering**.

## Some checks say "skipped"

Optional checks need optional packages. Install them in the same environment as the other packages:

| Check | Package |
| --- | --- |
| Email DNS (SPF, DMARC, DKIM, CAA) | `pip install dnspython` |
| Spell check | `pip install pyspellchecker`, then turn on **Spell check** in settings |
| HTML validation | `pip install html5lib` |

The browser sample needs Playwright and Chromium, like JavaScript rendering. It is skipped when **JavaScript / SPA rendering** is set to **Fast HTTP only**, or when **Browser audit sample** is off.

## A task I ticked came back

A tick is kept while the problem is still observed, marked "ticked, still observed". When the next capture no longer finds it, the task moves to Resolved. Keep the `^wo-` ID at the end of each line; it links the task to its finding.

## The capture finished but crawled zero pages

This is usually correct behavior. If robots.txt answers with a server error (5xx) or disallows everything, Web-Obs follows RFC 9309 and does not crawl. The Site health card shows the reason under Crawlability.

## "Could not write to the vault"

Check folder permissions. In a Flatpak or other sandbox, grant Obsidian access to the vault location. Diagnostics tests this with a small temporary file that it removes.

## Flatpak Obsidian cannot find your Python

Flatpak gives Obsidian its own filesystem view. Point the setting at a Python inside the vault or another location the sandbox can read, or grant access with Flatseal. The browser cache is also separate: Web-Obs checks the standard user cache as well as the sandbox one.

## Network checks fail

Captures need outbound HTTPS. Check VPN or proxy settings. Private and loopback addresses are blocked on purpose; for local testing only, set `WEB_OBS_LOCAL_TARGETS=127.0.0.1:PORT` when running the engine directly.

## A site blocks the capture or shows a challenge page

Web-Obs says plainly that it is a crawler (`WebObs` in the user agent) and does not disguise itself as a browser. Some sites answer crawlers with 403, a bot challenge or different HTML. That is the site's choice. Ask the owner to allow `WebObs`, or capture a site you run. If the site answers 429 (or 503 with `Retry-After`), Web-Obs waits and retries once, and after three such answers stops requesting new pages; the capture warnings say so. Try again later.

## A capture of one site is much slower than usual

The site's robots.txt sets `Crawl-delay`. Web-Obs then sends one request at a time with that gap (up to 60 seconds), so a 250 page capture with `Crawl-delay: 5` takes over 20 minutes. The capture warnings show the delay. Lower the page limit for a quicker capture.

## A user-triggered AI fetcher ignores my robots.txt

ChatGPT-User, Claude-User and Perplexity-User fetch pages on a person's request and may not follow robots.txt. Site Intel marks these separately from crawlers.

## Reporting a bug

Run diagnostics, press **Copy report**, and include it with the steps you took.
