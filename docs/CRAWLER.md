# The WebObs crawler

WebObs is an open source Obsidian plugin that saves a website into a local vault so its owner can study it: page notes, a 3D link map and an audit. Each capture runs on one person's computer, starts when that person asks for it, and reads public pages only. WebObs is not a search engine, does not train AI models and does not resell data.

If you run a website and found WebObs in your logs, this page explains what it sends and how to control it.

## How it identifies itself

Every HTTP request carries this user agent, where the version follows the release:

```
Mozilla/5.0 (compatible; WebObs/0.3.2; +https://github.com/AgriciDaniel/web-obs/blob/main/docs/CRAWLER.md)
```

- The robots.txt product token is `WebObs` (matched without regard to case).
- Filter your logs or firewall on `WebObs`.
- Pages rendered with a browser come from Playwright's bundled Chromium. They carry the same user agent, plus the standard Chromium client hint headers (`sec-ch-ua`, `sec-ch-ua-platform`), which describe the real browser engine.
- When a page loads in the browser, the scripts, styles and fonts it asks for load too, so those hosts (CDNs, font services) also see this user agent.
- WebObs does not rotate user agents, IP addresses or proxies, and does not try to get past bot protection. Requests come from the IP address of the person running the capture.

## What it requests

| Request | When |
|---|---|
| `/robots.txt` | First, before anything else on each origin. |
| Sitemaps named in robots.txt, `/sitemap.xml` and common variants | To find pages. |
| HTML pages | Up to the capture's page limit (250 by default). |
| Images, captions and transcripts on those pages | To keep a local copy, within size limits. |
| Discovery files such as `/llms.txt`, `/.well-known/security.txt`, `/humans.txt`, `/ads.txt`, `/manifest.webmanifest` | Once per capture, a small byte range each. |
| Stylesheets linked from the homepage | To read declared fonts and colours. |
| Linked destinations, internal and external | `HEAD` first, then a short ranged `GET` if needed, only to record the status code. Bodies are not kept. |
| A small sample of pages in a browser | Lab timing, an automated accessibility scan and a list of third party hosts. On by default, and the user can turn it off. |
| Full-page snapshots in a browser | One rendered load of up to 25 of the most important pages (the user can change or turn off the limit), to save a screenshot for their notes. |

Two checks touch your systems without an HTTP request, so they do not appear in web server logs:

- **TLS certificate:** one TLS handshake to port 443 to read the certificate's issuer and expiry. No HTTP request is sent on that connection.
- **Email DNS:** SPF, DMARC and MX lookups through the user's own DNS resolver. The user can turn this off.

## Politeness

- **robots.txt is followed** (RFC 9309), using the `WebObs` group if there is one and `*` otherwise. If robots.txt cannot be fetched because of a server error or rate limiting, WebObs does not crawl the site.
- **Crawl-delay is honoured.** If the matching group sets `Crawl-delay`, WebObs sends one request at a time to your site with at least that gap between them. Values above 60 seconds are treated as 60 seconds, and the capture says so.
- **Rate limits are respected.** On HTTP 429, or a 503 with `Retry-After`, WebObs pauses all requests to the site for the time given (30 seconds when a 429 has none, at most 5 minutes) and retries that page once. After three such answers, or a `Retry-After` longer than 5 minutes, it stops requesting new pages for the rest of the capture. A 503 without `Retry-After` is retried once later.
- **Low concurrency by default:** at most two requests at once to one origin, with a short gap between request starts.
- **Bounded:** a capture has a page limit, a link check limit and download size limits, and ends on its own.

## How to control it

Block it completely:

```
User-agent: WebObs
Disallow: /
```

Keep it out of part of the site:

```
User-agent: WebObs
Disallow: /private/
```

Slow it down:

```
User-agent: WebObs
Crawl-delay: 5
```

A `User-agent: WebObs` group replaces the `*` group for WebObs, as RFC 9309 describes, so repeat any `*` rules you also want applied.

## Questions or problems

Open an issue at [github.com/AgriciDaniel/web-obs/issues](https://github.com/AgriciDaniel/web-obs/issues). For a security report, see [SECURITY.md](../SECURITY.md).
