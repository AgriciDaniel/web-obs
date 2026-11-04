"""Readable names for per-page issue slugs. Shipped in the manifest so the UI and notes agree."""
from __future__ import annotations

import re

# slug: (category, tone, title, explanation)
ISSUES: dict[str, tuple[str, str, str, str]] = {
    "missing-title": ("pages", "attention", "Missing title", "The page has no title tag. Search results and browser tabs fall back to something generic."),
    "title-too-long": ("pages", "review", "Title longer than 65 characters", "Long titles are usually cut off in search results."),
    "title-too-short": ("pages", "review", "Title shorter than 20 characters", "A very short title rarely describes the page well enough to earn a click."),
    "missing-meta-description": ("pages", "review", "Missing meta description", "Search engines write their own snippet when none is given."),
    "meta-description-too-long": ("pages", "review", "Meta description longer than 165 characters", "Long descriptions are usually cut off in search results."),
    "missing-h1": ("pages", "review", "Missing H1", "No main heading was found on the page."),
    "multiple-h1": ("pages", "review", "More than one H1", "Several main headings make the page topic less clear."),
    "heading-level-skip": ("pages", "review", "Heading levels skip", "Headings jump a level, for example from H2 to H4, inside the main content."),
    "missing-canonical": ("pages", "review", "Missing canonical", "Without a canonical, search engines choose the preferred URL themselves."),
    "canonical-points-elsewhere": ("pages", "review", "Canonical points to another URL", "This page asks search engines to index a different URL instead."),
    "noindex": ("pages", "review", "Noindex in meta robots", "The page asks search engines not to index it."),
    "noindex-header": ("pages", "review", "Noindex in X-Robots-Tag header", "The response header asks search engines not to index the page."),
    "nofollow": ("pages", "review", "Nofollow on the page", "Search engines are asked not to follow any link on this page."),
    "missing-viewport": ("pages", "review", "Missing viewport tag", "Without a viewport tag, phones render the page zoomed out."),
    "invalid-jsonld": ("schema", "attention", "Invalid JSON-LD", "A structured data block could not be parsed as JSON."),
    "hreflang-missing-self": ("pages", "review", "Hreflang without a self reference", "Hreflang sets should include the page itself."),
    "images-missing-alt": ("accessibility", "review", "Images without alt text", "Screen readers and image search rely on alt text. Decorative images can use an empty alt."),
    "images-missing-dimensions": ("images", "review", "Images without width and height", "Missing dimensions let the layout jump while images load."),
    "generic-anchor-text": ("links", "review", "Generic link text", "Links such as \"click here\" say nothing about where they lead."),
    "page-broken": ("pages", "attention", "Page returned 404 or 410", "The page itself returned a missing or gone response."),
    "page-unavailable": ("pages", "coverage", "Page content unavailable", "The capture could not collect usable content. This is a collection gap."),
    "orphan-page": ("structure", "review", "Orphan page", "No captured route from the homepage reaches this page."),
    "unlisted-in-sitemap": ("structure", "review", "Missing from the sitemap", "The page was reached by links but is not in the sitemap."),
    "redirected-source-url": ("pages", "review", "Requested URL redirected", "The URL the capture requested redirected to another address."),
    "internal-link-form-mismatch": ("links", "review", "Links use a different URL form", "Internal links point at a variant of the published URL, for example without the trailing slash."),
    "low-text-ratio": ("content", "review", "Low text to HTML ratio", "Less than 10% of the HTML is visible text. Heavy markup or scripts can crowd out content."),
    "thin-content": ("content", "review", "Thin content", "Fewer than 200 words of visible body text. Fine for utility pages, weak for pages meant to rank."),
    "title-not-reflected-in-content": ("content", "review", "Title words missing from the body", "Most words of the title do not appear in the page text."),
    "description-not-reflected-in-content": ("content", "review", "Description words missing from the body", "Most words of the meta description do not appear in the page text."),
    "missing-doctype": ("pages", "review", "Missing HTML doctype", "Without <!doctype html> browsers fall back to quirks mode."),
    "missing-charset": ("pages", "review", "No character encoding declared", "Neither the response header nor a meta tag declares the encoding."),
    "charset-mismatch": ("pages", "review", "Header and meta charset disagree", "The response header and the meta tag declare different encodings."),
    "duplicate-meta-tags": ("pages", "review", "Duplicate meta tags", "The same meta tag, canonical or title appears more than once."),
    "meta-refresh-redirect": ("pages", "attention", "Meta refresh redirect", "The page redirects with a meta refresh. A server redirect is clearer for search engines."),
    "deprecated-html-tags": ("pages", "review", "Deprecated HTML tags", "Tags such as <center> or <font> are obsolete in HTML."),
    "uses-frames": ("pages", "attention", "Uses frames", "Content inside frames is hard for search engines to attribute."),
    "uses-flash": ("pages", "attention", "Uses Flash", "Flash no longer runs in any current browser."),
    "placeholder-text": ("content", "attention", "Placeholder text", "Lorem ipsum text was found in the page."),
    "html-over-3mb": ("pages", "attention", "HTML over 3 MB", "Very large HTML is slow to download and parse."),
    "missing-lang": ("accessibility", "review", "Missing lang attribute", "The html element does not declare the page language."),
    "links-to-http": ("security", "review", "Links to insecure http:// URLs", "An HTTPS page links to plain HTTP addresses."),
    "mixed-content": ("security", "attention", "Mixed content", "An HTTPS page loads images, scripts or styles over plain HTTP. Browsers block or warn about these."),
    "render-blocking-resources": ("pages", "review", "Render-blocking scripts or styles", "Scripts without async or defer and stylesheets in the head delay the first paint."),
    "large-dom": ("pages", "review", "Large DOM (over 1,500 elements)", "Big documents use more memory and slow down style and layout work."),
    "deep-dom": ("pages", "review", "Deep DOM (over 32 levels)", "Deep nesting makes rendering and scripts slower."),
    "wide-dom-node": ("pages", "review", "An element with over 60 children", "One parent with many direct children is slow to lay out."),
    "url-too-long": ("structure", "review", "URL longer than 115 characters", "Long URLs are harder to share and are often cut off."),
    "url-has-parameters": ("structure", "review", "URL with query parameters", "Parameters can create duplicate versions of the same page."),
    "url-uppercase": ("structure", "review", "Uppercase letters in the URL", "URLs are case sensitive, so mixed case invites duplicates and broken links."),
    "url-underscores": ("structure", "review", "Underscores in the URL", "Hyphens are the usual word separator in URLs."),
    "url-non-ascii": ("structure", "review", "Non-ASCII characters in the URL", "These need encoding and can break when copied."),
    "url-double-slash": ("structure", "review", "Double slash in the URL path", "Double slashes often create accidental duplicate URLs."),
    "missing-open-graph": ("content", "review", "No Open Graph tags", "Shared links show no title or image on social platforms."),
    "missing-og-image": ("content", "review", "No og:image", "Shared links show no preview image."),
    "og-url-differs-from-canonical": ("content", "review", "og:url differs from the canonical", "Social shares may point at a different URL than search engines."),
    "first-image-lazy-loaded": ("images", "review", "First image is lazy loaded", "The main image often is the largest paint. Lazy loading it delays the page."),
    "no-compression": ("pages", "review", "HTML served without compression", "No gzip or Brotli encoding was used for this response."),
    "form-inputs-without-label": ("accessibility", "review", "Form fields without a label", "Screen readers cannot tell what these fields are for."),
    "buttons-without-name": ("accessibility", "review", "Buttons without an accessible name", "Buttons with no text or label are announced as just \"button\"."),
    "links-without-text": ("accessibility", "review", "Links without text", "Links with no text or label are announced without a destination."),
    "possible-misspellings": ("content", "review", "Possible misspellings", "Words not found in the English dictionary. Names and jargon appear here too."),
}

_COUNT_RE = re.compile(r"\s*\((\d+)\)$")


def base_slug(issue: str) -> str:
    return _COUNT_RE.sub("", issue).strip()


def describe(issue: str) -> dict:
    slug = base_slug(issue)
    category, tone, title, explanation = ISSUES.get(slug, ("pages", "review", slug.replace("-", " ").capitalize(), "A signal recorded by the capture."))
    m = _COUNT_RE.search(issue)
    return {"slug": slug, "category": category, "tone": tone, "title": title, "explanation": explanation,
            "count": int(m.group(1)) if m else None}


def catalog_for_manifest() -> dict:
    return {slug: {"category": c, "tone": t, "title": title, "explanation": e} for slug, (c, t, title, e) in ISSUES.items()}
