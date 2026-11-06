"""Readable names for per-page issue slugs. Shipped in the manifest so the UI and notes agree."""
from __future__ import annotations

import re

# slug: (category, tone, title, explanation)
ISSUES: dict[str, tuple[str, str, str, str]] = {
    "missing-title": ("pages", "attention", "Missing title", "The page has no title tag. Google then builds the search result title from other text, such as the main heading, and browser tabs show the bare address. Add a short, descriptive title so you control it."),
    "title-too-long": ("pages", "review", "Title longer than 65 characters", "Long titles are usually cut off in search results."),
    "title-too-short": ("pages", "review", "Title shorter than 20 characters", "A very short title rarely describes the page well enough to earn a click."),
    "missing-meta-description": ("pages", "review", "Missing meta description", "Search engines write their own snippet when none is given."),
    "meta-description-too-long": ("pages", "review", "Meta description longer than 165 characters", "Long descriptions are usually cut off in search results."),
    "missing-h1": ("pages", "review", "Missing H1", "No main heading was found on the page."),
    "multiple-h1": ("pages", "review", "More than one H1", "Google says there is no ideal number of headings, so this does not affect Search on its own. Check that the most prominent heading names the page, because Google can use it for the search result title."),
    "heading-level-skip": ("accessibility", "review", "Heading levels skip", "Headings jump a level, for example from H2 to H4, inside the main content. Google Search does not mind heading order, but screen reader users move through pages by heading level, so skipped levels can confuse them."),
    "missing-canonical": ("pages", "review", "Missing canonical", "Without a canonical, search engines choose the preferred URL themselves."),
    "canonical-points-elsewhere": ("pages", "review", "Canonical points to another URL", "This page asks search engines to index a different URL instead."),
    "noindex": ("pages", "review", "Noindex in meta robots", "The page asks search engines not to index it."),
    "noindex-header": ("pages", "review", "Noindex in X-Robots-Tag header", "The response header asks search engines not to index the page."),
    "nofollow": ("pages", "review", "Nofollow on the page", "Search engines are asked not to follow any link on this page."),
    "missing-viewport": ("pages", "review", "Missing viewport tag", "Without a viewport tag, phones render the page zoomed out."),
    "invalid-jsonld": ("schema", "review", "Invalid JSON-LD", "A structured data block could not be parsed as JSON, so search engines cannot read any of it. The page can still be indexed and rank, but it loses any rich result that block was meant to support. Fix the syntax and test it in the Rich Results Test."),
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
    "thin-content": ("content", "review", "Little body text (under 200 words)", "Fewer than 200 words of visible body text were found. Google has no minimum word count, so this is not a ranking rule. Check that the page fully answers what a visitor came for. Product, contact and other utility pages are often fine when short. Not measured for languages written without spaces, such as Chinese, Japanese and Thai."),
    "title-not-reflected-in-content": ("content", "review", "Title words missing from the body", "Most words of the title do not appear in the page text."),
    "description-not-reflected-in-content": ("content", "review", "Description words missing from the body", "Most words of the meta description do not appear in the page text."),
    "missing-doctype": ("pages", "review", "Missing HTML doctype", "Without <!doctype html> browsers fall back to quirks mode."),
    "missing-charset": ("pages", "review", "No character encoding declared", "Neither the response header nor a meta tag declares the encoding."),
    "charset-mismatch": ("pages", "review", "Header and meta charset disagree", "The response header and the meta tag declare different encodings."),
    "duplicate-meta-tags": ("pages", "review", "Duplicate meta tags", "The same meta tag, canonical or title appears more than once."),
    "meta-refresh-redirect": ("pages", "review", "Meta refresh redirect", "The page redirects with a meta refresh. Google follows it: an instant refresh counts as a permanent redirect and a delayed one as temporary. A server side 301 or 308 redirect is the most reliable choice when your platform allows it."),
    "deprecated-html-tags": ("pages", "review", "Deprecated HTML tags", "Tags such as <center> or <font> are obsolete in HTML."),
    "uses-frames": ("pages", "attention", "Uses frames", "Content inside frames is hard for search engines to attribute."),
    "uses-flash": ("pages", "attention", "Uses Flash", "Flash no longer runs in any current browser."),
    "placeholder-text": ("content", "attention", "Placeholder text", "Lorem ipsum text was found in the page."),
    "html-over-2mb": ("pages", "attention", "HTML over 2 MB", "Googlebot reads only the first 2 MB of an HTML file when crawling for Google Search, measured before compression. Text, links and markup after that point are not considered for indexing. Move large inline scripts, styles or data out of the HTML."),
    "html-over-3mb": ("pages", "attention", "HTML over 3 MB", "Googlebot reads only the first 2 MB of an HTML file when crawling for Google Search, measured before compression, so part of this page is not considered for indexing. Captures made after this check changed report it as HTML over 2 MB."),
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
    "url-non-ascii": ("structure", "review", "Unencoded non-ASCII characters in the URL", "Words in your audience's language are fine in URLs, and Google recommends them. Links to the page should use the percent encoded (UTF-8) form so the address does not break when copied or shared."),
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
