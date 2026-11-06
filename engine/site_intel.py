#!/usr/bin/env python3
"""
Website Analytics, Tech Stack, Security, Conversion Funnel, 2026 Agentic/GEO
Readiness, Robots Policy, and direct outbound link checks for web-obs.
All observations come from published website resources, without enrichment APIs.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse, urlsplit, urlunparse

from url_safety import DEFAULT_REQUEST_HEADERS, RequestDeadlineExceeded, URLSafetyError, safe_requests_session

# The public robots.txt product name (RFC 9309) that WebObs answers to. Not a credential.
ROBOTS_PRODUCT_NAME = "WebObs"

# Token sources: OpenAI, Anthropic, Perplexity, Google, Apple, Meta, Common Crawl and Amazon list their tokens in
# their own crawler documentation. Bytespider and DuckAssistBot are widely documented by crawler trackers but
# have no vendor page that states the robots.txt token (checked 2026-11-03), so treat those two as community-sourced.
AI_BOT_TOKENS = (
    ("GPTBot", "OpenAI Training"),
    ("OAI-SearchBot", "ChatGPT Search"),
    ("OAI-AdsBot", "OpenAI Ads Landing Page Check"),
    ("ChatGPT-User", "ChatGPT User Fetch"),
    ("ClaudeBot", "Anthropic Training"),
    ("Claude-SearchBot", "Claude Search"),
    ("Claude-User", "Claude User Fetch"),
    ("PerplexityBot", "Perplexity Search"),
    ("Perplexity-User", "Perplexity User Fetch"),
    ("meta-externalagent", "Meta AI Training"),
    ("Amazonbot", "Amazon Alexa and AI"),
    ("Bytespider", "ByteDance AI"),
    ("DuckAssistBot", "DuckDuckGo AI Answers"),
    ("Google-Extended", "Google Gemini/AI"),
    ("Applebot-Extended", "Apple Intelligence"),
    ("CCBot", "Common Crawl"),
)

# Normalize country/mobile/www subdomains of major platforms so graphs don't split e.g. md.linkedin.com vs linkedin.com
PLATFORM_APEX_DOMAINS = (
    "linkedin.com",
    "youtube.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
    "x.com",
    "twitter.com",
)

ANALYTICS_SIGNATURES: list[tuple[str, str, tuple[str, ...]]] = [
    ("Google Analytics 4", "analytics", ("gtag('config', 'g-", 'gtag("config", "g-', "googletagmanager.com/gtag/js")),
    ("Google Tag Manager", "tag-manager", ("googletagmanager.com/gtm.js", "gtm.start")),
    ("Google Ads Conversion", "ads", ("googleadservices.com/pagead/conversion", "gtag('config', 'aw-", 'gtag("config", "aw-')),
    ("Meta Pixel", "ads", ("connect.facebook.net", "fbq('init'", 'fbq("init"')),
    ("LinkedIn Insight Tag", "ads", ("snap.licdn.com/li.lms-analytics", "_linkedin_partner_id")),
    ("TikTok Pixel", "ads", ("analytics.tiktok.com", "ttq.load")),
    ("X / Twitter Pixel", "ads", ("static.ads-twitter.com", "twq('init'")),
    ("Microsoft Clarity", "heatmap", ("clarity.ms/tag/",)),
    ("Hotjar", "heatmap", ("static.hotjar.com", "hjsettings")),
    ("PostHog", "product-analytics", ("app.posthog.com", "us.i.posthog.com", "eu.i.posthog.com", "posthog.init")),
    ("Mixpanel", "product-analytics", ("cdn.mxpnl.com", "mixpanel.init")),
    ("Amplitude", "product-analytics", ("cdn.amplitude.com", "amplitude.getinstance")),
    ("Segment", "cdp", ("cdn.segment.com/analytics.js",)),
    ("Plausible Analytics", "privacy-analytics", ("plausible.io/js/",)),
    ("Umami Analytics", "privacy-analytics", ("umami.is/script.js", "data-website-id=")),
    ("Fathom Analytics", "privacy-analytics", ("cdn.usefathom.com",)),
    ("Matomo", "privacy-analytics", ("matomo.js", "piwik.js", "_paq.push")),
    ("Cloudflare Web Analytics", "privacy-analytics", ("static.cloudflareinsights.com/beacon.min.js",)),
    ("Vercel Analytics", "privacy-analytics", ("/_vercel/insights/script.js",)),
    ("HubSpot", "crm-marketing", ("js.hs-scripts.com", "js.hsforms.net", "hs-analytics")),
    ("Intercom", "chat-support", ("widget.intercom.io", "intercomsettings")),
    ("Crisp Chat", "chat-support", ("client.crisp.chat", "crisp_website_id")),
    ("Drift", "chat-support", ("js.driftt.com",)),
    ("Tawk.to", "chat-support", ("embed.tawk.to",)),
    ("Zendesk Widget", "chat-support", ("static.zdassets.com",)),
    ("Klaviyo", "email-marketing", ("static.klaviyo.com",)),
    ("Mailchimp", "email-marketing", ("chimpstatic.com", "list-manage.com")),
    ("Kit / ConvertKit", "email-marketing", ("ck.page", "convertkit.com")),
    ("ActiveCampaign", "email-marketing", ("trackcmp.net",)),
    ("RB2B", "b2b-intent", ("ddwl4m2hdecbv.cloudfront.net", "rb2b.com")),
]

CMP_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("Cookiebot", ("consent.cookiebot.com", "id=\"cookiebot\"")),
    ("OneTrust", ("cdn.cookielaw.org", "optanonwrapper")),
    ("Complianz", ("complianz-gdpr", "cmplz-cookiebanner")),
    ("CookieYes", ("cdn-cookieyes.com", "cky-consent")),
    ("Osano", ("cmp.osano.com",)),
    ("Termly", ("app.termly.io",)),
    ("Iubenda", ("cdn.iubenda.com",)),
    ("Usercentrics", ("app.usercentrics.eu",)),
    ("Didomi", ("sdk.privacy-center.org",)),
    ("Borlabs Cookie", ("borlabs-cookie",)),
]

REVIEW_PLATFORM_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("Trustpilot", ("widget.trustpilot.com", "trustpilot.com/review/")),
    ("G2", ("g2.com/products/", "g2crowd.com")),
    ("Capterra", ("capterra.com/p/", "capterra.com/reviews/")),
    ("Clutch", ("widget.clutch.co", "clutch.co/profile/")),
    ("Senja", ("widget.senja.io", "senja.io/p/")),
    ("Testimonial.to", ("testimonial.to/",)),
    ("Reviews.io", ("widget.reviews.io", "reviews.io/company-reviews")),
    ("Yotpo", ("staticw2.yotpo.com",)),
    ("Judge.me", ("cdn.judge.me", "jdgm-widget")),
    ("Elfsight Reviews", ("apps.elfsight.com",)),
]

CMS_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("WordPress", ("/wp-content/", "/wp-includes/", 'name="generator" content="wordpress')),
    ("Webflow", ("data-wf-site=", "data-wf-page=", "website-files.com")),
    ("Shopify", ("cdn.shopify.com", "shopify.theme")),
    ("Framer", ("framerusercontent.com", 'name="generator" content="framer')),
    ("Wix", ("static.wixstatic.com", "wix-warmup-data")),
    ("Squarespace", ("static1.squarespace.com", "squarespace-cdn.com")),
    ("Ghost", ('name="generator" content="ghost', "/ghost/api/")),
    ("Next.js", ("/_next/static/", "__next_data__")),
    ("Astro", ("/_astro/", 'name="generator" content="astro')),
    ("Nuxt", ("/_nuxt/", "__nuxt__")),
    ("SvelteKit", ("__sveltekit", "/_app/immutable/")),
    ("Gatsby", ('id="___gatsby"', 'name="generator" content="gatsby')),
    ("Docusaurus", ('name="generator" content="docusaurus',)),
    ("VitePress", ("vitepress", "vp-doc")),
    ("Hugo", ('name="generator" content="hugo',)),
    ("Jekyll", ('name="generator" content="jekyll',)),
]

FUNNEL_PLATFORMS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Calendly", "booking", ("calendly.com/",)),
    ("Cal.com", "booking", ("cal.com/",)),
    ("SavvyCal", "booking", ("savvycal.com/",)),
    ("HubSpot Meetings", "booking", ("meetings.hubspot.com/", "meetings-eu1.hubspot.com/")),
    ("Typeform", "form-survey", ("typeform.com/",)),
    ("Tally", "form-survey", ("tally.so/",)),
    ("Jotform", "form-survey", ("jotform.com/",)),
    ("Stripe Checkout", "payments", ("checkout.stripe.com/", "buy.stripe.com/")),
    ("Gumroad", "payments", ("gumroad.com/",)),
    ("Lemon Squeezy", "payments", ("lemonsqueezy.com/",)),
    ("Paddle", "payments", ("paddle.com/",)),
    ("Whop", "payments", ("whop.com/",)),
    ("Skool", "community", ("skool.com/",)),
    ("Circle", "community", ("circle.so/",)),
    ("Discord", "community", ("discord.gg/", "discord.com/invite/")),
    ("WhatsApp", "messaging", ("wa.me/", "api.whatsapp.com/")),
    ("Telegram", "messaging", ("t.me/",)),
]

SECURITY_HEADERS_SPEC = (
    ("strict-transport-security", "HSTS"),
    ("content-security-policy", "CSP"),
    ("x-frame-options", "X-Frame-Options"),
    ("x-content-type-options", "X-Content-Type-Options"),
    ("referrer-policy", "Referrer-Policy"),
    ("permissions-policy", "Permissions-Policy"),
)


HSTS_MIN_SECONDS = 15552000  # 180 days, the long-standing minimum for a meaningful HSTS policy


def hsts_max_age(value: str) -> Optional[int]:
    match = re.search(r"max-age\s*=\s*\"?(\d+)", value or "", re.I)
    return int(match.group(1)) if match else None


def summarize_header_consistency(per_page: dict[str, dict[str, str]]) -> dict:
    """Compare security headers across sampled pages so one lucky homepage does not hide gaps elsewhere."""
    pages = {url: {k.lower(): str(v) for k, v in (headers or {}).items()} for url, headers in per_page.items()}
    rows = []
    for key, label in SECURITY_HEADERS_SPEC:
        missing_on = sorted(url for url, headers in pages.items() if not headers.get(key, "").strip())
        present = len(pages) - len(missing_on)
        state = "none" if present == 0 else "all" if not missing_on else "some"
        rows.append({"header": label, "presentOn": present, "of": len(pages), "state": state, "missingOn": missing_on[:5]})
    notes = []
    for url, headers in pages.items():
        value = headers.get("strict-transport-security", "")
        age = hsts_max_age(value) if value else None
        if value and (age is None or age < HSTS_MIN_SECONDS):
            notes.append(f"HSTS max-age is {'missing' if age is None else age} on {url}; at least {HSTS_MIN_SECONDS} is recommended.")
            break
    return {"sampledPages": len(pages), "headers": rows,
            "inconsistent": [row["header"] for row in rows if row["state"] == "some"], "notes": notes}


def canonicalize_external_domain(hostname: str) -> str:
    h = (hostname or "").lower().strip().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    for apex in PLATFORM_APEX_DOMAINS:
        if h == apex or h.endswith(f".{apex}"):
            return apex
    return h


def is_clean_social_profile_url(url: str) -> Optional[str]:
    """
    Return normalized profile URL if `url` points to a real brand/author social profile
    (filtering out deep /blob/, /commit/, /issues/, /watch, /share, /status/ links).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = canonicalize_external_domain(parsed.hostname or "")
    path = (parsed.path or "/").rstrip("/")
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None

    if host == "github.com":
        if len(segments) == 1 and segments[0].lower() not in (
            "features",
            "pricing",
            "login",
            "join",
            "orgs",
            "topics",
            "marketplace",
            "settings",
            "sponsors",
        ):
            return f"https://github.com/{segments[0]}"
        return None

    if host == "linkedin.com":
        if len(segments) == 2 and segments[0].lower() in ("in", "company", "school"):
            return f"https://www.linkedin.com/{segments[0].lower()}/{segments[1]}"
        return None

    if host == "youtube.com":
        if len(segments) == 1 and segments[0].startswith("@"):
            return f"https://www.youtube.com/{segments[0]}"
        if len(segments) == 2 and segments[0].lower() in ("channel", "c", "user"):
            return f"https://www.youtube.com/{segments[0].lower()}/{segments[1]}"
        return None

    if host in ("x.com", "twitter.com"):
        if len(segments) == 1 and segments[0].lower() not in ("intent", "share", "home", "explore", "i", "search"):
            return f"https://x.com/{segments[0]}"
        return None

    if host in ("instagram.com", "tiktok.com"):
        if len(segments) == 1 and segments[0].lower() not in ("p", "reel", "explore", "stories"):
            return f"https://www.{host}/{segments[0]}"
        return None

    if host == "facebook.com":
        if len(segments) == 1 and segments[0].lower() not in ("sharer", "sharer.php", "share.php", "dialog"):
            return f"https://www.facebook.com/{segments[0]}"
        return None

    if host == "skool.com":
        if len(segments) == 1:
            return f"https://www.skool.com/{segments[0]}"
        return None

    return None


def detect_analytics_and_stack(
    html_samples: list[str],
    home_headers: dict[str, str],
    all_external_urls: Optional[list[str]] = None,
) -> dict:
    combined_lower = "\n".join(h.lower() for h in html_samples[:8])
    combined_raw = "\n".join(html_samples[:8])
    ext_lower = "\n".join(u.lower() for u in (all_external_urls or [])[:300])
    corpus_lower = f"{combined_lower}\n{ext_lower}"

    detected_tools: list[dict] = []
    seen_tools: set[str] = set()
    for name, category, needles in ANALYTICS_SIGNATURES:
        if any(n in combined_lower for n in needles):
            if name not in seen_tools:
                seen_tools.add(name)
                detected_tools.append({"name": name, "category": category})

    ga4_ids = sorted(set(re.findall(r"\bG-[A-Z0-9]{6,12}\b", combined_raw)))[:6]
    gtm_ids = sorted(set(re.findall(r"\bGTM-[A-Z0-9]{5,10}\b", combined_raw)))[:6]
    gads_ids = sorted(set(re.findall(r"\bAW-[0-9]{6,12}\b", combined_raw)))[:6]

    if ga4_ids and "Google Analytics 4" not in seen_tools:
        detected_tools.append({"name": "Google Analytics 4", "category": "analytics"})
    if gtm_ids and "Google Tag Manager" not in seen_tools:
        detected_tools.append({"name": "Google Tag Manager", "category": "tag-manager"})

    gsc_verified = "google-site-verification" in combined_lower
    bing_verified = "msvalidate.01" in combined_lower

    cms_detected: list[str] = []
    for cms_name, needles in CMS_SIGNATURES:
        if any(n in combined_lower for n in needles):
            cms_detected.append(cms_name)
    if not cms_detected:
        cms_detected.append("Custom HTML / Static or SSR")

    cookie_consent_tools: list[str] = []
    for cmp_name, needles in CMP_SIGNATURES:
        if any(n in combined_lower for n in needles):
            cookie_consent_tools.append(cmp_name)

    review_platforms: list[str] = []
    for rev_name, needles in REVIEW_PLATFORM_SIGNATURES:
        if any(n in corpus_lower for n in needles):
            review_platforms.append(rev_name)

    headers_lower = {k.lower(): str(v) for k, v in (home_headers or {}).items()}
    hosting_hints: list[str] = []
    server_hdr = headers_lower.get("server", "")
    powered_hdr = headers_lower.get("x-powered-by", "")

    if "cf-ray" in headers_lower or "cloudflare" in server_hdr.lower():
        hosting_hints.append("Cloudflare")
    if "x-vercel-id" in headers_lower or "vercel" in server_hdr.lower():
        hosting_hints.append("Vercel")
    if "x-nf-request-id" in headers_lower or "netlify" in server_hdr.lower():
        hosting_hints.append("Netlify")
    if "x-github-request-id" in headers_lower or "github.com" in server_hdr.lower():
        hosting_hints.append("GitHub Pages")
    if "x-amz-cf-id" in headers_lower:
        hosting_hints.append("AWS CloudFront")
    if "x-served-by" in headers_lower and "cache-" in headers_lower.get("x-served-by", "").lower():
        hosting_hints.append("Fastly")
    if server_hdr and server_hdr.lower() not in ("cloudflare", "vercel", "netlify", "github.com"):
        hosting_hints.append(f"Server: {server_hdr[:40]}")
    if powered_hdr:
        hosting_hints.append(f"Powered-By: {powered_hdr[:40]}")

    present_sec: list[str] = []
    missing_sec: list[str] = []
    for hdr_key, label in SECURITY_HEADERS_SPEC:
        if hdr_key in headers_lower and headers_lower[hdr_key].strip():
            present_sec.append(label)
        else:
            missing_sec.append(label)

    return {
        "analyticsAndPixels": detected_tools,
        "measurementIds": {
            "ga4": ga4_ids,
            "gtm": gtm_ids,
            "googleAds": gads_ids,
        },
        "searchConsoleVerifiedMeta": gsc_verified,
        "bingVerifiedMeta": bing_verified,
        "cmsOrFramework": cms_detected,
        "hostingAndCdn": hosting_hints,
        "cookieConsentTools": cookie_consent_tools,
        "reviewPlatforms": review_platforms,
        "httpCompression": headers_lower.get("content-encoding") or None,
        "cacheControl": headers_lower.get("cache-control") or None,
        "securityHeaders": {
            "present": present_sec,
            "missing": missing_sec,
        },
    }


def detect_funnel_platforms(all_external_urls: list[str]) -> list[dict]:
    found: dict[str, dict] = {}
    for u in all_external_urls:
        ul = u.lower()
        for label, kind, needles in FUNNEL_PLATFORMS:
            if any(n in ul for n in needles):
                if label not in found:
                    found[label] = {"platform": label, "category": kind, "urls": []}
                if u not in found[label]["urls"] and len(found[label]["urls"]) < 8:
                    found[label]["urls"].append(u)
    return list(found.values())


def _robots_agent_token(value: str) -> str:
    """RFC 9309 product token: "*" alone, or the leading run of letters, "_" and "-".

    "GPTBot/1.1" and "GPTBot*" are gptbot. An empty value or one with no valid token ("80legs", "008", "*bot") gives "",
    which still starts a group, one that matches no crawler: its rules must not join the group above.
    """
    if re.fullmatch(r"\*\s*", value or ""):
        return "*"
    token = re.match(r"[A-Za-z_-]+", value or "")
    return token.group(0).lower() if token else ""


def _parse_robots_groups(robots_text: str) -> tuple[dict[str, list[tuple[str, str]]], Optional[str]]:
    groups: dict[str, list[tuple[str, str]]] = {}
    current_agents: list[str] = []
    seen_rule_in_group = False
    content_signal_val: Optional[str] = None

    for raw_line in (robots_text or "").lstrip("\ufeff").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, val = line.split(":", 1)
        f_low = field.strip().lower()
        v_clean = val.strip()

        if f_low == "user-agent":
            # An empty or invalid value still starts a group, one that matches no crawler ("" from the helper).
            agent_token = _robots_agent_token(v_clean)
            if seen_rule_in_group:
                current_agents, seen_rule_in_group = [], False
            if agent_token:  # an invalid token still starts a group, one that matches no crawler
                current_agents.append(agent_token)
                groups.setdefault(agent_token, [])
        elif f_low in ("allow", "disallow"):
            seen_rule_in_group = True
            for ag in current_agents:
                groups.setdefault(ag, []).append((f_low, v_clean))
        elif f_low == "content-signal" and v_clean and not content_signal_val:
            content_signal_val = v_clean

    return groups, content_signal_val


MAX_CRAWL_DELAY_SEC = 60.0


def _parse_crawl_delays(robots_text: str) -> dict[str, float]:
    """Crawl-delay per user-agent group. Not part of RFC 9309, but widely used to ask bots to slow down."""
    delays: dict[str, float] = {}
    current_agents: list[str] = []
    seen_rule_in_group = False
    for raw_line in (robots_text or "").lstrip("\ufeff").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, val = line.split(":", 1)
        f_low, v_clean = field.strip().lower(), val.strip()
        if f_low == "user-agent":
            agent_token = _robots_agent_token(v_clean)  # the same groups as the rules, empty values included
            if seen_rule_in_group:
                current_agents, seen_rule_in_group = [], False
            if agent_token:
                current_agents.append(agent_token)
        elif f_low in ("allow", "disallow"):
            seen_rule_in_group = True
        elif f_low == "crawl-delay" and current_agents:
            seen_rule_in_group = True
            try:
                value = float(v_clean)
            except ValueError:
                continue
            if value != value or value < 0:  # NaN or negative
                continue
            for agent in current_agents:
                delays.setdefault(agent, value)
    return delays


def _match_robots_path(path_and_query: str, pattern: str) -> bool:
    if not pattern:
        return False
    end_anchor = pattern.endswith("$")
    pat = pattern[:-1] if end_anchor else pattern
    # Greedy wildcard matching avoids regex backtracking on untrusted rules.
    target = _robots_octets(path_and_query, pattern=False)
    pat = _robots_octets(pat, pattern=True)
    i = j = 0
    star = -1
    retry = 0
    while i < len(target):
        if j == len(pat) and not end_anchor:
            return True
        if j < len(pat) and pat[j] == "*":
            star, retry = j, i
            j += 1
        elif j < len(pat) and pat[j] == target[i]:
            i += 1
            j += 1
        elif star >= 0:
            retry += 1
            i, j = retry, star + 1
        else:
            return False
    while j < len(pat) and pat[j] == "*":
        j += 1
    return j == len(pat)


def _robots_octets(value: str, *, pattern: bool) -> str:
    """Normalize UTF-8 and unreserved escapes without decoding reserved escapes."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    output = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "%" and re.fullmatch(r"[0-9a-fA-F]{2}", value[i + 1:i + 3] or ""):
            octet = int(value[i + 1:i + 3], 16)
            decoded = chr(octet)
            output.append(decoded if decoded in unreserved else f"%{octet:02X}")
            i += 3
            continue
        if ord(ch) > 127:
            output.extend(f"%{octet:02X}" for octet in ch.encode("utf-8"))
        elif ch in "*$" and not (pattern and ch == "*"):
            output.append(f"%{ord(ch):02X}")
        else:
            output.append(ch)
        i += 1
    return "".join(output)


def _robots_rules_for_agent(groups: dict, user_agent: str) -> tuple[list, list[str]]:
    # The browser-shaped header still identifies this crawler as WebObs.
    product = ROBOTS_PRODUCT_NAME if re.search(r"\bWebObs(?:/|\b)", user_agent, re.I) else user_agent.split("/", 1)[0].strip()
    key = product.lower()
    if key in groups:
        return groups[key], [key]
    return groups.get("*", []), ["*"] if "*" in groups else []


def build_robots_policy(
    robots_text: str,
    status_code: Optional[int],
    error: Optional[str] = None,
    too_large: bool = False,
    user_agent: str = DEFAULT_REQUEST_HEADERS["User-Agent"],
) -> dict:
    """Build a serializable fetch-state-aware policy; uncertain fetches deny crawl.

    RFC 9309 permits access for unavailable 4xx responses. WebObs additionally
    defers on 429 rather than continuing against a rate-limited origin.
    """
    state, can_crawl, reason = "unknown", False, "Robots policy could not be established."
    rules, matched_agents = [], []
    crawl_delay: Optional[float] = None
    if error or too_large:
        reason = str(error) if error else "Robots response exceeded the byte limit."
    elif isinstance(status_code, int) and 200 <= status_code < 300:
        state, can_crawl, reason = "parsed", True, "Fetched robots rules apply to WebObs."
        groups, _ = _parse_robots_groups(robots_text)
        rules, matched_agents = _robots_rules_for_agent(groups, user_agent)
        delays = _parse_crawl_delays(robots_text)
        product = ROBOTS_PRODUCT_NAME.lower() if re.search(r"\bWebObs\b", user_agent, re.I) else user_agent.split("/", 1)[0].strip().lower()
        # The most specific group wins, as for allow and disallow rules.
        crawl_delay = delays.get(product, delays.get("*") if product not in groups else None)
    elif status_code in (404, 410):
        state, can_crawl, reason = "absent", True, "Robots file is absent."
    elif isinstance(status_code, int) and 400 <= status_code < 500 and status_code != 429:
        state, can_crawl, reason = "unavailable", True, "Robots file is unavailable (HTTP 4xx); RFC 9309 permits crawling."
    elif status_code == 429:
        reason = "Robots request was rate limited; crawling is deferred."
    elif isinstance(status_code, int) and status_code >= 500:
        reason = "Robots server failed; crawling is deferred."
    return {
        "state": state, "statusCode": status_code, "userAgent": user_agent,
        "productToken": ROBOTS_PRODUCT_NAME if re.search(r"\bWebObs\b", user_agent, re.I) else user_agent.split("/", 1)[0],
        "canCrawl": can_crawl, "reason": reason, "matchedAgents": matched_agents,
        "crawlDelaySec": crawl_delay,
        "rules": [[directive, pattern] for directive, pattern in rules],
    }


def robots_url_decision(policy: dict, url: str) -> dict:
    """Return an explicit allowed/disallowed/unknown decision for one URL."""
    if not policy.get("canCrawl"):
        return {"allowed": False, "status": "unknown", "reason": policy.get("reason", "Unknown robots policy."), "matchedPattern": None}
    try:
        parsed = urlsplit(url)  # urlsplit keeps ";params" in the path, which rules must see (RFC 9309)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Not an HTTP URL")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
    except ValueError:
        return {"allowed": False, "status": "unknown", "reason": "Invalid crawl URL.", "matchedPattern": None}
    if parsed.path == "/robots.txt":
        return {"allowed": True, "status": "allowed", "reason": "Robots file is implicitly allowed.", "matchedPattern": None}
    best_len, best_directive, best_pattern = -1, "allow", None
    for directive, pattern in policy.get("rules", []):
        if not pattern or directive not in ("allow", "disallow"):
            continue
        if _match_robots_path(target, pattern):
            # Specificity is the length of the rule path as written, "*" and "$" included: Google's example
            # "allow: /page" against "disallow: /*.htm" for /page.htm is disallowed, because /*.htm is longer.
            # Each percent-encoded octet counts once. An exact tie goes to allow (least restrictive).
            specificity = len(re.sub(r"%[0-9A-F]{2}", "_", _robots_octets(pattern, pattern=True)))
            if specificity > best_len or (specificity == best_len and directive == "allow"):
                best_len, best_directive, best_pattern = specificity, directive, pattern
    allowed = best_directive != "disallow"
    return {
        "allowed": allowed, "status": "allowed" if allowed else "disallowed",
        "reason": ("Matched robots " + best_directive + " rule.") if best_pattern else policy.get("reason", "No matching robots rule."),
        "matchedPattern": best_pattern,
    }


def is_url_allowed_by_robots(
    robots_text: str, url: str, user_agent: str = DEFAULT_REQUEST_HEADERS["User-Agent"],
) -> str:
    """Compatibility helper for known text; fetch-aware callers use the policy."""
    policy = build_robots_policy(robots_text, 200 if robots_text else 404, user_agent=user_agent)
    decision = robots_url_decision(policy, url)
    return "allowed (no robots.txt)" if policy["state"] == "absent" else decision["status"]


MAX_DISCOVERY_REDIRECTS = 3
# User-triggered fetchers may ignore robots.txt, so a "blocked" result is a request, not a guarantee.
USER_TRIGGERED_AI_BOTS = ("ChatGPT-User", "Claude-User", "Perplexity-User")


def validate_llms_txt(text: str, base_url: Optional[str] = None, content_type: Optional[str] = None) -> dict:
    """Check llms.txt against the llmstxt.org format. The full rules live in llms_txt.py."""
    from llms_txt import validate_llms_txt as _validate
    return _validate(text, base_url=base_url, content_type=content_type)


def validate_security_txt(text: str, now: Optional[datetime] = None) -> dict:
    """Check RFC 9116: Contact and exactly one Expires field are required; Expires must be in the future."""
    now = now or datetime.now(timezone.utc)
    fields: dict[str, list[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, _, value = line.partition(":")
        fields.setdefault(name.strip().lower(), []).append(value.strip())
    issues: list[str] = []
    expires_iso = None
    if not fields.get("contact"):
        issues.append("missing-contact")
    expires = fields.get("expires", [])
    if not expires:
        issues.append("missing-expires")
    else:
        if len(expires) > 1:
            issues.append("multiple-expires")
        try:
            stamp = expires[0].strip().upper()  # RFC 3339 allows lowercase t and z
            parsed = datetime.fromisoformat(stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            expires_iso = parsed.isoformat()
            if parsed < now:
                issues.append("expired")
        except ValueError:
            issues.append("invalid-expires")
    return {"valid": not issues, "issues": issues, "expires": expires_iso}


def _same_site(a: str, b: str) -> bool:
    """Same site means the same host ignoring a leading www and the http/https scheme choice."""
    pa, pb = urlparse(a), urlparse(b)
    strip = lambda h: (h or "").lower().removeprefix("www.")
    return pa.scheme in ("http", "https") and pb.scheme in ("http", "https") and strip(pa.hostname) == strip(pb.hostname)


def _fetch_following(session, target: str, allowed, skipped: list, **kwargs):
    """GET with up to three redirects that stay on the same site and pass each origin's robots check.

    The allowed callback evaluates the robots policy of the URL's own origin, so a redirect to www
    or to https is judged by that origin's rules. Redirects to other sites are recorded and not followed.
    Returns the final streamed response (caller closes it) or None.
    """
    current = target
    for _ in range(MAX_DISCOVERY_REDIRECTS + 1):
        resp = session.get(current, allow_redirects=False, **kwargs)
        if not 300 <= resp.status_code < 400:
            return resp
        location = resp.headers.get("Location")
        resp.close()
        if not location:
            return None
        nxt = urljoin(current, location)
        if not _same_site(target, nxt):
            skipped.append({"url": target, "status": "unknown", "reason": f"Redirected to a different site ({urlparse(nxt).netloc}); not followed.", "redirectedTo": nxt})
            return None
        if not allowed(nxt):
            return None
        current = nxt
    skipped.append({"url": target, "status": "unknown", "reason": f"More than {MAX_DISCOVERY_REDIRECTS} redirects; not followed."})
    return None


def analyze_robots(robots_text: str) -> dict:
    """Plain findings about robots.txt that affect crawling and rendering."""
    groups, content_signal = _parse_robots_groups(robots_text)
    star = groups.get("*", [])
    blanket = any(d == "disallow" and v == "/" for d, v in star) and not any(d == "allow" for d, _ in star)
    asset_hits = sorted({v for d, v in star if d == "disallow" and re.search(r"\.(css|js)\b|/wp-includes|/wp-content/(themes|plugins)|/assets|/static", v, re.I)})
    return {
        "blanketDisallow": blanket,
        "blocksAssets": asset_hits[:10],
        "hasSitemapLine": bool(re.search(r"^\s*sitemap\s*:", robots_text or "", re.I | re.M)),
        "contentSignal": content_signal,
    }


def parse_robots_ai_policy(robots_text: str) -> dict[str, str]:
    """
    Evaluate robots.txt policy for major AI crawlers using RFC 9309 group precedence
    (specific named group overrides wildcard `*`).
    """
    if not robots_text or not robots_text.strip():
        return {bot: "allowed (no robots.txt)" for bot, _ in AI_BOT_TOKENS}

    result: dict[str, str] = {}
    for bot_token, _desc in AI_BOT_TOKENS:
        policy = build_robots_policy(robots_text, 200, user_agent=bot_token)
        decision = robots_url_decision(policy, "https://robots-policy.invalid/")
        status = "allowed" if decision["allowed"] else "blocked"
        result[bot_token] = status + (" (via *)" if policy["matchedAgents"] == ["*"] else "")

    return result


def probe_ai_and_discovery_endpoints(
    origin: str,
    site_root: str,
    robots_text: str,
    html_samples: Optional[list[str]] = None,
    robots_policy: Optional[dict] = None,
) -> dict:
    """
    Probe 2026 Agentic Web & Discovery standards:
    - /llms.txt, /llms-full.txt (saved locally when present)
    - /.well-known/ai-catalog.json, /.well-known/agent.json, /.well-known/agents.json, /.well-known/mcp.json
    - /.well-known/security.txt, /ads.txt
    - HTTP Markdown for Agents content negotiation (Accept: text/markdown, Vary: accept,
      x-markdown-tokens, Content-Signal)
    - WebMCP client markers (navigator.modelContext / webmcp) & alternate text/markdown links
    """
    ai_bots = parse_robots_ai_policy(robots_text)
    _, robots_content_signal = _parse_robots_groups(robots_text)

    saved_files: list[str] = []
    endpoints: dict[str, bool] = {
        "llmsTxt": False,
        "llmsFullTxt": False,
        "aiCatalogJson": False,
        "agentJson": False,
        "mcpJson": False,
        "securityTxt": False,
        "adsTxt": False,
        "apiCatalog": False,
        "humansTxt": False,
        "webManifest": False,
    }
    site_checks: dict[str, dict] = {}

    validation: dict[str, dict] = {}
    # Whether the llms.txt checks got an answer, so a missing file is told apart from a failed request.
    llms_probe: dict[str, dict] = {key: {"state": "not-checked"} for key in ("llmsTxt", "llmsFullTxt")}
    markdown_negotiation = {
        "supported": False,
        "varyAccept": False,
        "markdownTokensHeader": None,
        "contentSignalHeader": None,
        "robotsContentSignal": robots_content_signal,
    }

    checks = [
        ("/llms.txt", "llmsTxt", "llms.txt", "text"),
        ("/llms-full.txt", "llmsFullTxt", "llms-full.txt", "text"),
        ("/.well-known/ai-catalog.json", "aiCatalogJson", None, "json"),
        ("/.well-known/agent.json", "agentJson", "agent.json", "json"),
        ("/.well-known/agents.json", "agentJson", None, "json"),
        ("/.well-known/mcp.json", "mcpJson", None, "json"),
        ("/.well-known/api-catalog", "apiCatalog", None, "json"),
        ("/.well-known/security.txt", "securityTxt", None, "text"),
        ("/ads.txt", "adsTxt", None, "text"),
        ("/humans.txt", "humansTxt", None, "text"),
        ("/manifest.webmanifest", "webManifest", None, "json"),
    ]
    policy = robots_policy if robots_policy is not None else build_robots_policy(robots_text, 200)
    if robots_policy is not None and not policy["canCrawl"]:
        ai_bots = {bot: "unknown (robots fetch incomplete)" for bot, _ in AI_BOT_TOKENS}
    elif policy["state"] == "parsed" and not robots_text.strip():
        ai_bots = {bot: "allowed (empty robots.txt)" for bot, _ in AI_BOT_TOKENS}
    skipped = []
    origin_key = lambda u: f"{urlparse(u).scheme}://{urlparse(u).netloc.lower()}"
    policies = {origin_key(origin): policy}
    holder = {}

    def policy_for(url):
        key = origin_key(url)
        if key not in policies:
            text, status, err = "", None, "Robots request failed."
            try:
                r = _fetch_following(holder["session"], key + "/robots.txt", lambda u: True, [], timeout=4.0, stream=True)
                if r is not None:
                    try:
                        status = r.status_code
                        err = None
                        text = r.raw.read(512 * 1024, decode_content=True).decode("utf-8", errors="replace") if status == 200 else ""
                    finally:
                        r.close()
            except Exception:
                pass
            policies[key] = build_robots_policy(text, status, err)
        return policies[key]

    def allowed(target):
        if urlparse(target).path == "/robots.txt":
            return True
        decision = robots_url_decision(policy_for(target), target)
        if not decision["allowed"]:
            skipped.append({"url": target, "reason": decision["reason"], "status": decision["status"]})
        return decision["allowed"]

    try:
        with safe_requests_session(origin) as session:
            holder["session"] = session
            session.headers.update({"User-Agent": DEFAULT_REQUEST_HEADERS["User-Agent"]})

            # 1. HTTP Markdown for Agents negotiation probe on origin root
            try:
                if not allowed(f"{origin.rstrip('/')}/"):
                    raise ValueError("Root probe refused by robots policy")
                md_resp = session.get(
                    f"{origin.rstrip('/')}/",
                    headers={
                        "User-Agent": DEFAULT_REQUEST_HEADERS["User-Agent"],
                        "Accept": "text/markdown, text/x-markdown;q=0.9, text/html;q=0.1",
                    },
                    timeout=4.0,
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if 300 <= md_resp.status_code < 400:
                        skipped.append({"url": f"{origin.rstrip('/')}/", "status": "unknown", "reason": "Discovery redirects are not followed."})
                    hdrs_low = {k.lower(): str(v) for k, v in md_resp.headers.items()} if md_resp.status_code == 200 else {}
                    ctype_md = hdrs_low.get("content-type", "").lower()
                    if "text/markdown" in ctype_md or "text/x-markdown" in ctype_md:
                        markdown_negotiation["supported"] = True
                    vary_hdr = hdrs_low.get("vary", "").lower()
                    if "accept" in vary_hdr:
                        markdown_negotiation["varyAccept"] = True
                    if "x-markdown-tokens" in hdrs_low:
                        markdown_negotiation["markdownTokensHeader"] = hdrs_low["x-markdown-tokens"]
                    if "content-signal" in hdrs_low:
                        markdown_negotiation["contentSignalHeader"] = hdrs_low["content-signal"]
                finally:
                    md_resp.close()
            except Exception:
                pass

            # 2. Well-known & AI discovery endpoints
            for rel_url, key, save_name, expected_kind in checks:
                if endpoints.get(key) and not save_name:
                    continue
                target = f"{origin.rstrip('/')}{rel_url}"
                tracked = key in llms_probe
                if not allowed(target):
                    if tracked:
                        llms_probe[key] = {"state": "refused", "detail": "robots.txt does not allow fetching it."}
                    continue
                try:
                    resp = _fetch_following(session, target, allowed, skipped, timeout=4.0, stream=True)
                    if resp is None:
                        if tracked:
                            llms_probe[key] = {"state": "not-checked", "detail": "It redirects to another site, which is not followed."}
                        continue
                    try:
                        status = resp.status_code
                        if status != 200:
                            if tracked:
                                llms_probe[key] = ({"state": "absent", "statusCode": status} if status in (404, 410)
                                                   else {"state": "unavailable", "statusCode": status, "detail": f"HTTP {status}."})
                            continue
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if "text/html" in ctype:
                            if tracked:
                                llms_probe[key] = {"state": "html", "statusCode": status, "contentType": ctype.split(";")[0].strip()}
                            continue
                        limit = 512 * 1024
                        raw = resp.raw.read(limit, decode_content=True)
                        text = raw.decode("utf-8", errors="replace").strip()
                        if not text or text.lstrip().lower().startswith(("<!doctype html", "<html")):
                            if tracked:
                                llms_probe[key] = {"state": "html" if text else "absent", "statusCode": status,
                                                   "detail": "Empty response." if not text else "HTML returned."}
                            continue
                        if expected_kind == "json":
                            json.loads(text)
                        if key == "llmsTxt":
                            validation[key] = validate_llms_txt(text, base_url=resp.url or target, content_type=ctype)
                        elif key == "llmsFullTxt":
                            from llms_txt import validate_llms_full_txt
                            validation[key] = validate_llms_full_txt(text, content_type=ctype)
                        elif key == "securityTxt":
                            validation[key] = validate_security_txt(text)
                        # Marked found only after validation, so a validation crash never reads as a clean recheck.
                        endpoints[key] = True
                        if tracked:
                            llms_probe[key] = {"state": "found", "statusCode": status, "url": resp.url or target,
                                               "contentType": ctype.split(";")[0].strip() or None, "truncated": len(raw) >= limit}
                        if save_name and save_name not in saved_files:
                            out_path = os.path.join(site_root, save_name)
                            with open(out_path, "w", encoding="utf-8") as f:
                                f.write(text + "\n")
                            saved_files.append(save_name)
                    finally:
                        resp.close()
                except Exception as exc:
                    if tracked and llms_probe[key]["state"] != "found":
                        llms_probe[key] = {"state": "not-checked", "detail": f"Request failed ({type(exc).__name__})."}
                    continue

            # 3. Site level checks: https redirect, www/non-www duplicate, soft 404
            parsed_origin = urlparse(origin)
            host = parsed_origin.hostname or ""

            def _probe(name, url, classify):
                try:
                    if not allowed(url):
                        site_checks[name] = {"state": "skipped", "detail": "Refused by robots policy."}
                        return
                    r = session.get(url, timeout=4.0, stream=True, allow_redirects=False)
                    try:
                        site_checks[name] = classify(r.status_code, r.headers.get("Location") or "")
                    finally:
                        r.close()
                except URLSafetyError:
                    site_checks[name] = {"state": "not-resolving", "detail": "Host does not resolve to a public address."}
                except Exception:
                    site_checks[name] = {"state": "unreachable", "detail": "Request failed."}

            if parsed_origin.scheme == "https" and not parsed_origin.port:
                def classify_http(code, loc):
                    if code in (301, 308) and loc.lower().startswith("https://"):
                        return {"state": "ok", "detail": f"HTTP redirects permanently to HTTPS ({code}).", "statusCode": code}
                    if 300 <= code < 400 and loc.lower().startswith("https://"):
                        return {"state": "warn", "detail": f"HTTP redirects to HTTPS with a temporary {code}.", "statusCode": code}
                    if code == 200:
                        return {"state": "fail", "detail": "HTTP serves content without redirecting to HTTPS.", "statusCode": code}
                    return {"state": "warn", "detail": f"HTTP responded {code} without an HTTPS redirect.", "statusCode": code}
                _probe("httpToHttps", f"http://{parsed_origin.netloc}/", classify_http)

                alt_host = host.removeprefix("www.") if host.startswith("www.") else f"www.{host}"
                def classify_alt(code, loc):
                    if 300 <= code < 400 and _same_site(f"https://{alt_host}/", loc) and urlparse(loc).hostname == host:
                        return {"state": "ok", "detail": f"{alt_host} redirects to {host} ({code}).", "statusCode": code}
                    if code == 200:
                        return {"state": "warn", "detail": f"{alt_host} serves content too; pick one canonical host.", "statusCode": code}
                    return {"state": "warn", "detail": f"{alt_host} responded {code}.", "statusCode": code}
                _probe("alternateHost", f"https://{alt_host}/", classify_alt)

            def classify_404(code, loc):
                if code in (404, 410):
                    return {"state": "ok", "detail": f"Unknown URLs return {code}.", "statusCode": code}
                if code == 200:
                    return {"state": "fail", "detail": "Unknown URLs return 200 (soft 404).", "statusCode": code}
                if 300 <= code < 400:
                    return {"state": "warn", "detail": f"Unknown URLs redirect ({code}); confirm the destination is not the homepage.", "statusCode": code}
                return {"state": "warn", "detail": f"Unknown URLs return {code}.", "statusCode": code}
            _probe("soft404", f"{origin.rstrip('/')}/webobs-probe-{uuid.uuid4().hex[:12]}", classify_404)
    except (URLSafetyError, Exception):
        pass

    combined_html_low = "\n".join(h.lower() for h in (html_samples or [])[:6])
    web_mcp_detected = any(
        tok in combined_html_low
        for tok in ("navigator.modelcontext", "webmcp", "registertool(", "modelcontext.providecontext")
    )
    md_link_alt = 'type="text/markdown"' in combined_html_low or "type='text/markdown'" in combined_html_low

    blocked_bots = [b for b, status in ai_bots.items() if status.startswith("blocked")]
    allowed_bots = [b for b, status in ai_bots.items() if status.startswith("allowed")]

    return {
        "endpoints": endpoints,
        "savedFiles": saved_files,
        "markdownNegotiation": markdown_negotiation,
        "webMcpDetected": web_mcp_detected,
        "markdownLinkAlternate": md_link_alt,
        "aiBotsPolicy": ai_bots,
        "userTriggeredBots": [b for b in USER_TRIGGERED_AI_BOTS if b in ai_bots],
        "validation": validation,
        "llmsProbe": llms_probe,
        "siteChecks": site_checks,
        "robotsFindings": analyze_robots(robots_text),
        "allowedAiBotsCount": len(allowed_bots),
        "blockedAiBots": blocked_bots,
        "robotsSkipped": skipped,
    }


def _external_target_identity(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("Not an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None or any(c.isspace() for c in url):
        raise ValueError("URL credentials or whitespace are not permitted")
    host = parsed.hostname.lower().rstrip(".")
    host = "[" + host + "]" if ":" in host else host.encode("idna").decode("ascii")
    port = parsed.port
    if port is not None and port != (443 if parsed.scheme.lower() == "https" else 80):
        host += ":" + str(port)
    return urlunparse((parsed.scheme.lower(), host, parsed.path or "/", parsed.params, parsed.query, ""))


def _check_direct_external_url(url: str, deadline: float, request_timeout: float) -> dict:
    row = {"url": url, "finalUrl": url, "status": "unknown", "statusCode": None,
           "attempted": True, "reason": "", "redirectChain": [], "method": "HEAD"}
    current, method = url, "HEAD"
    visited = set()
    try:
        for _hop in range(6):
            identity = (current, method)
            if identity in visited:
                row["reason"] = "Redirect loop."
                return row
            visited.add(identity)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                row["reason"] = "Link-check time budget reached."
                return row
            with safe_requests_session(current) as session:
                timeout = max(0.001, min(request_timeout, remaining / 2))
                response = session.request(
                    method, current, headers={**DEFAULT_REQUEST_HEADERS, "Range": "bytes=0-1024"},
                    timeout=timeout, allow_redirects=False, stream=True,
                )
                try:
                    status = response.status_code
                    row.update({"finalUrl": current, "statusCode": status, "method": method})
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            row["reason"] = "Redirect has no Location header."
                            return row
                        row["redirectChain"].append({"url": current, "statusCode": status})
                        current = _external_target_identity(urljoin(current, location))
                        continue
                    if status in (404, 410, 405, 501) and method == "HEAD":
                        # Some live sites reject HEAD for working pages. A
                        # missing result becomes definitive only after GET.
                        row.update(headStatusCode=status, statusCode=None, method="GET")
                        method = "GET"
                        continue
                    if 200 <= status < 300:
                        row.update(status="ok", reason="Direct HTTP response observed.")
                    elif status in (404, 410):
                        row.update(status="broken", reason="Target returned HTTP 404 or 410 on GET confirmation.")
                    elif 500 <= status < 600:
                        row.update(status="server-error", reason="Target server failed; this is not proof of a dead link.")
                    else:
                        row["reason"] = "Access-limited or inconclusive HTTP response."
                    return row
                finally:
                    response.close()
        row["reason"] = "Redirect or method-fallback limit reached."
    except URLSafetyError:
        row["reason"] = "Target or redirect refused by URL safety."
    except RequestDeadlineExceeded as exc:
        row["reason"] = f"Direct check failed: {exc}"
    except Exception as exc:
        row["reason"] = "Direct check failed: " + type(exc).__name__
    return row


def check_external_links(
    external_urls: list[str], max_checks: int = 1000, max_seconds: float = 30,
    request_timeout: float = 3,
) -> dict:
    """Check every unique supplied target within explicit count and time budgets.

    No platform is silently skipped. Unattempted and inconclusive results remain
    visible. The time budget is checked between requests; OS DNS resolution may
    exceed it. HEAD fallback GET is streamed and the body is never consumed.
    """
    deadline = time.monotonic() + max(0, max_seconds)
    budget = max(0, int(max_checks))
    targets = []
    seen = set()
    for raw in external_urls:
        try:
            target = _external_target_identity(raw)
            invalid = False
        except (ValueError, TypeError, UnicodeError):
            target = str(raw)
            invalid = True
        if target not in seen:
            seen.add(target)
            targets.append((target, invalid))
    results = []
    attempted = 0
    for target, invalid in targets:
        reason = "Unsupported or invalid URL." if invalid else "Link-check count budget reached."
        if not invalid and time.monotonic() >= deadline:
            reason = "Link-check time budget reached."
        if invalid or attempted >= budget or time.monotonic() >= deadline:
            results.append({"url": target, "finalUrl": target, "status": "unchecked", "statusCode": None,
                            "attempted": False, "reason": reason, "redirectChain": [], "method": None})
            continue
        attempted += 1
        results.append(_check_direct_external_url(target, deadline, max(0.001, request_timeout)))
    return summarize_link_results(results, budget, max_seconds)


def summarize_link_results(results, budget=1000, max_seconds=30):
    """Aggregate retained outcomes without repeating network requests."""
    attempted = sum(bool(row.get('attempted')) for row in results)
    unknown = [row for row in results if row["status"] == "unknown"]
    unchecked = [row for row in results if not row["attempted"]]
    return {
        "totalCount": len(results), "checkedCount": attempted, "attemptedCount": attempted,
        "uncheckedCount": len(unchecked), "unknownCount": len(unknown),
        "assessedCount": sum(row["status"] in ("ok", "broken", "server-error") for row in results),
        "coverageComplete": not unchecked and not unknown, "allAttempted": not unchecked,
        "results": results, "brokenLinks": [row for row in results if row["status"] == "broken"],
        "serverErrors": [row for row in results if row["status"] == "server-error"],
        "unknownLinks": unknown, "uncheckedLinks": unchecked,
        "maxChecks": budget, "maxSeconds": max(0, max_seconds),
    }


def check_sampled_external_links(external_urls: list[str], max_checks: int = 20) -> dict:
    """Compatibility wrapper; all omitted targets are now explicitly unchecked."""
    return check_external_links(external_urls, max_checks=max_checks)
