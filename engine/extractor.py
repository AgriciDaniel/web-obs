#!/usr/bin/env python3
"""
Step 2 & Step 3 of web-obs: Page fetching, byte-level SHA-256 receipts,
full-fidelity semantic Markdown conversion, lazy-aware local image & inline SVG
downloading, JSON-LD entity distillation, commercial/CTA/navigation/legal signal
extraction, technical SEO audit checks, and link classification.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from markdown_converter import convert_html_to_markdown
from resources import classify_resource, extract_resource_references, fetch_asset, srcset_urls
from site_intel import canonicalize_external_domain
from sitemap import canonicalize_crawl_url, is_same_site_host
from page_fetch import fetch_page_html


try:
    import lxml  # noqa: F401

    _HTML_PARSER = "lxml"
except ImportError:
    _HTML_PARSER = "html.parser"

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    from htmldate import find_date
except ImportError:
    find_date = None

_LAZY_SRC_ATTRS = (
    "data-perfmatters-src",
    "data-ewww-src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-full-url",
)

_IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

_GENERIC_ANCHORS = frozenset(
    {
        "click here",
        "read more",
        "learn more",
        "here",
        "more",
        "link",
        "this page",
        "details",
        "view",
        "website",
        "continue",
        "go",
    }
)

_CTA_VERB_PREFIX_RE = re.compile(
    r"^(book|start|get|try|buy|join|schedule|download|request|explore|claim|install|contact|apply|subscribe|watch|sign up|create|launch|talk to|work with)\b",
    re.I,
)

_LEGAL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Privacy Policy", ("/privacy", "privacy policy", "privacy notice")),
    ("Terms of Service", ("/terms", "terms of service", "terms and conditions", "terms of use")),
    ("Cookie Policy", ("/cookie", "cookie policy")),
    ("Refund Policy", ("/refund", "refund policy", "cancellation policy")),
    ("Security", ("/security", "security policy", "trust center")),
    ("Imprint / Legal", ("/imprint", "/impressum", "/legal", "legal notice")),
)

_COPYRIGHT_RE = re.compile(
    r"(?:©|\(c\)|copyright)\s*(?:19|20)\d{2}(?:\s*[-/]\s*(?:19|20)?\d{2})?\s*([^\n|•]{2,90})",
    re.I,
)

_PRICE_SNIPPET_RE = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d{1,2})?(?:\s*/\s*(?:mo|month|yr|year|seat|user))?|\bfree forever\b)",
    re.I,
)

_PROOF_CLAIM_RE = re.compile(
    r"(?:\b[+-]?\d[\d,.]*\s?(?:%|k\+|m\+|x)\s+[a-zA-Z]{3,}|\b\d[\d,.]*[kKmM]?\+?\s+(?:stars|users|clients|customers|clicks|views|companies|agencies|teams|downloads|reviews|pages)\b)",
    re.I,
)

MAX_IMAGE_BYTES = 12 * 1024 * 1024


def is_crawlable_page_url(url: str) -> bool:
    """Keep landing pages while excluding published non-HTML resource hints."""
    return classify_resource(url)['type'] == 'page'


def _is_in_chrome_zone(tag: Tag) -> bool:
    """True when an anchor sits inside site-wide navigation, header, footer, breadcrumb, or aside."""
    curr: Optional[Tag] = tag.parent if isinstance(tag.parent, Tag) else None
    while curr is not None:
        name = (curr.name or "").lower()
        if name in ("nav", "header", "footer", "aside"):
            return True
        role = (curr.get("role") or "").lower()
        if role in ("navigation", "banner", "contentinfo", "complementary", "menubar"):
            return True
        classes = " ".join(curr.get("class") or []).lower()
        el_id = (curr.get("id") or "").lower()
        marker = f"{classes} {el_id}"
        if any(
            tok in marker
            for tok in (
                "navbar",
                "topbar",
                "top-bar",
                "site-header",
                "site-footer",
                "main-nav",
                "footer-nav",
                "mega-menu",
                "breadcrumb",
                "cookie-banner",
                "sidebar-nav",
            )
        ):
            return True
        curr = curr.parent if isinstance(curr.parent, Tag) else None
    return False


def _resolve_best_img_src(img: Tag, base_url: str) -> Optional[str]:
    candidates: list[str] = []
    for attr in _LAZY_SRC_ATTRS:
        val = img.get(attr)
        if isinstance(val, str) and val.strip() and not val.strip().startswith("data:"):
            candidates.append(val.strip())
    raw_src = img.get("src")
    if isinstance(raw_src, str) and raw_src.strip() and not raw_src.strip().startswith("data:"):
        candidates.append(raw_src.strip())
    if not candidates:
        for srcset_attr in ("data-srcset", "srcset"):
            srcset = img.get(srcset_attr)
            if isinstance(srcset, str) and srcset.strip():
                parts = [p for p in srcset_urls(srcset) if p and not p.startswith(("data:", "blob:"))]
                if parts:
                    candidates.append(parts[-1])
                    break
    if not candidates:
        return None
    full = urljoin(base_url, candidates[0])
    parsed = urlparse(full)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return full


def _clean_anchor_summary(a_tag: Tag) -> str:
    """
    Extract a crisp, human-readable anchor label even when <a> wraps an entire
    feature card (<div><h3>Title</h3><p>Long description...</p></div>).
    """
    heading = a_tag.find(["h1", "h2", "h3", "h4", "h5", "h6", "strong"])
    if isinstance(heading, Tag):
        h_txt = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
        if h_txt and len(h_txt) >= 2:
            return h_txt[:90]

    raw = re.sub(r"\s+", " ", a_tag.get_text(" ", strip=True)).strip()
    if raw:
        if len(raw) <= 85:
            return raw
        cut = raw[:82].rsplit(" ", 1)[0]
        return f"{cut}..."

    img_child = a_tag.find("img")
    if isinstance(img_child, Tag) and img_child.get("alt"):
        return f"[img: {str(img_child.get('alt')).strip()[:70]}]"
    if a_tag.get("aria-label"):
        return str(a_tag.get("aria-label")).strip()[:85]
    return ""


def _format_schema_address(addr) -> str:
    if isinstance(addr, str):
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            str(addr.get(k) or "").strip()
            for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")
        ]
        return ", ".join(p for p in parts if p)
    return ""


def _distill_schema_entities(schema_blocks: list[dict], page_url: str) -> dict:
    organizations: list[dict] = []
    offers_products: list[dict] = []
    people: list[dict] = []
    faqs: list[dict] = []

    def _types_of(item: dict) -> list[str]:
        t = item.get("@type")
        if isinstance(t, list):
            return [str(x) for x in t if isinstance(x, str)]
        if isinstance(t, str):
            return [t]
        return []

    for item in schema_blocks:
        if not isinstance(item, dict):
            continue
        types = _types_of(item)

        # Organization / LocalBusiness / Brand
        if any(
            t in (
                "Organization",
                "Corporation",
                "LocalBusiness",
                "ProfessionalService",
                "MedicalBusiness",
                "Store",
                "Restaurant",
                "EducationalOrganization",
                "Brand",
            )
            for t in types
        ):
            logo_val = item.get("logo")
            if isinstance(logo_val, dict):
                logo_val = logo_val.get("url")
            same_as = item.get("sameAs")
            if isinstance(same_as, str):
                same_as = [same_as]
            elif not isinstance(same_as, list):
                same_as = []
            organizations.append(
                {
                    "type": types[0],
                    "name": str(item.get("name") or "").strip(),
                    "legalName": str(item.get("legalName") or "").strip(),
                    "description": str(item.get("description") or "").strip()[:240],
                    "url": str(item.get("url") or "").strip(),
                    "logo": urljoin(page_url, str(logo_val)) if isinstance(logo_val, str) and logo_val else "",
                    "email": str(item.get("email") or "").strip(),
                    "telephone": str(item.get("telephone") or "").strip(),
                    "address": _format_schema_address(item.get("address")),
                    "priceRange": str(item.get("priceRange") or "").strip(),
                    "sameAs": [str(s) for s in same_as if isinstance(s, str)][:12],
                }
            )

        # Product / SoftwareApplication / Service / Course / Offer
        if any(
            t in ("Product", "SoftwareApplication", "WebApplication", "Service", "Course", "Offer")
            for t in types
        ):
            offers_raw = item.get("offers")
            offer_obj = offers_raw[0] if isinstance(offers_raw, list) and offers_raw else (offers_raw if isinstance(offers_raw, dict) else item)
            agg = item.get("aggregateRating") if isinstance(item.get("aggregateRating"), dict) else {}
            offers_products.append(
                {
                    "type": types[0],
                    "name": str(item.get("name") or "").strip(),
                    "description": str(item.get("description") or "").strip()[:200],
                    "price": str(offer_obj.get("price") if offer_obj.get("price") is not None else offer_obj.get("lowPrice", "")).strip() if isinstance(offer_obj, dict) else "",
                    "currency": str(offer_obj.get("priceCurrency") or "").strip() if isinstance(offer_obj, dict) else "",
                    "availability": str(offer_obj.get("availability") or "").strip().rsplit("/", 1)[-1] if isinstance(offer_obj, dict) and offer_obj.get("availability") else "",
                    "ratingValue": str(agg.get("ratingValue") or "").strip(),
                    "reviewCount": str(agg.get("reviewCount") or agg.get("ratingCount") or "").strip(),
                }
            )

        # Person or Article author
        if "Person" in types and item.get("name"):
            people.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "jobTitle": str(item.get("jobTitle") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                }
            )
        elif isinstance(item.get("author"), dict) and item["author"].get("name"):
            au = item["author"]
            people.append(
                {
                    "name": str(au.get("name") or "").strip(),
                    "jobTitle": str(au.get("jobTitle") or "").strip(),
                    "url": str(au.get("url") or "").strip(),
                }
            )

        # FAQPage Q&A pairs
        if "FAQPage" in types:
            main_ent = item.get("mainEntity")
            q_list = main_ent if isinstance(main_ent, list) else ([main_ent] if isinstance(main_ent, dict) else [])
            for q_item in q_list[:12]:
                if not isinstance(q_item, dict):
                    continue
                q_txt = re.sub(r"\s+", " ", str(q_item.get("name") or "")).strip()
                ans_obj = q_item.get("acceptedAnswer")
                a_raw = ans_obj.get("text") if isinstance(ans_obj, dict) else ""
                a_txt = re.sub(r"<[^>]+>", " ", str(a_raw or ""))
                a_txt = re.sub(r"\s+", " ", a_txt).strip()
                if q_txt and a_txt:
                    faqs.append({"question": q_txt[:180], "answer": a_txt[:360]})

    return {
        "organizations": organizations[:6],
        "offersAndProducts": offers_products[:10],
        "people": people[:10],
        "faqs": faqs[:12],
    }


def extract_page_data(
    html: str,
    page_url: str,
    target_host: str,
    response_headers: Optional[dict[str, str]] = None,
) -> dict:
    """
    Parse HTML and return rich SEO, JSON-LD entity, CTA/offer/navigation/legal,
    full-fidelity Markdown, local asset inventory, internal/external links, and
    deterministic technical SEO audit flags.
    """
    soup = BeautifulSoup(html, _HTML_PARSER)
    hdrs_low = {k.lower(): str(v) for k, v in (response_headers or {}).items()}
    x_robots_tag = hdrs_low.get("x-robots-tag", "").strip()

    html_tag = soup.find("html")
    html_lang = ""
    if isinstance(html_tag, Tag) and html_tag.get("lang"):
        html_lang = str(html_tag.get("lang")).strip()

    title = ""
    if soup.title:
        title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()

    meta_description = ""
    meta_robots = ""
    author = ""
    og_title = ""
    og_image = ""
    og_site_name = ""
    og_type = ""
    twitter_card = ""
    twitter_site = ""
    theme_color = ""
    published_date = ""
    modified_date = ""

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower().strip()
        prop = (meta.get("property") or "").lower().strip()
        content = (meta.get("content") or "").strip()
        if not content:
            continue
        if name == "description" and not meta_description:
            meta_description = content
        elif prop == "og:description" and not meta_description:
            meta_description = content
        elif prop == "og:title" and not og_title:
            og_title = content
        elif name == "robots":
            meta_robots = content
        elif name == "author" and not author:
            author = content
        elif prop == "og:image" and not og_image:
            og_image = urljoin(page_url, content)
        elif prop == "og:site_name" and not og_site_name:
            og_site_name = content
        elif prop == "og:type" and not og_type:
            og_type = content
        elif name == "twitter:card" and not twitter_card:
            twitter_card = content
        elif name == "twitter:site" and not twitter_site:
            twitter_site = content
        elif name == "theme-color" and not theme_color:
            theme_color = content
        elif prop in ("article:published_time", "og:published_time") and not published_date:
            published_date = content
        elif prop in ("article:modified_time", "og:updated_time") and not modified_date:
            modified_date = content

    if not published_date and find_date is not None:
        try:
            detected = find_date(html, url=page_url)
            if detected:
                published_date = detected
        except Exception:
            pass

    canonical = ""
    favicon = ""
    hreflang_links: list[dict] = []
    rss_feeds: list[str] = []
    markdown_alternates: list[str] = []

    for link_el in soup.find_all("link"):
        rel_raw = link_el.get("rel") or []
        rels = [str(r).lower() for r in (rel_raw.split() if isinstance(rel_raw, str) else rel_raw)]
        href = (link_el.get("href") or "").strip()
        if not href:
            continue
        full_l = urljoin(page_url, href)
        ltype = (link_el.get("type") or "").lower().strip()

        if "canonical" in rels and not canonical:
            canonical = full_l
        elif ("icon" in rels or "apple-touch-icon" in rels) and not favicon:
            favicon = full_l
        elif "alternate" in rels:
            hlang = (link_el.get("hreflang") or "").strip()
            if hlang:
                hreflang_links.append({"lang": hlang, "url": full_l})
            if ltype in ("application/rss+xml", "application/atom+xml") and full_l not in rss_feeds:
                rss_feeds.append(full_l)
            if ltype == "text/markdown" and full_l not in markdown_alternates:
                markdown_alternates.append(full_l)

    # Heading hierarchy + level-skip check in DOM order
    headings: dict[str, list[str]] = {"h1": [], "h2": [], "h3": [], "h4": []}
    heading_level_skips = 0
    prev_h_level: Optional[int] = None
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if h.get("aria-hidden") == "true":
            continue
        txt = re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip()
        if not txt:
            continue
        lvl = int(h.name[1])
        if prev_h_level is not None and lvl > prev_h_level + 1:
            heading_level_skips += 1
        prev_h_level = lvl
        if h.name in headings:
            headings[h.name].append(txt)

    schema_types: list[str] = []
    schema_blocks: list[dict] = []
    jsonld_invalid = 0
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw_json = script.string or script.get_text()
        if not raw_json:
            continue
        try:
            parsed = json.loads(raw_json)
            items = []
            if isinstance(parsed, dict):
                items = parsed.get("@graph", [parsed]) if "@graph" in parsed else [parsed]
            elif isinstance(parsed, list):
                items = parsed
            for item in items:
                if isinstance(item, dict):
                    if len(schema_blocks) < 20:
                        schema_blocks.append(item)
                    if "@type" in item:
                        t = item["@type"]
                        if isinstance(t, list):
                            for sub in t:
                                if isinstance(sub, str) and sub not in schema_types:
                                    schema_types.append(sub)
                        elif isinstance(t, str) and t not in schema_types:
                            schema_types.append(t)
                    if not published_date and isinstance(item.get("datePublished"), str):
                        published_date = item["datePublished"]
                    if not modified_date and isinstance(item.get("dateModified"), str):
                        modified_date = item["dateModified"]
                    if not author and isinstance(item.get("author"), dict) and item["author"].get("name"):
                        author = str(item["author"]["name"]).strip()
        except Exception:
            jsonld_invalid += 1

    schema_entities = _distill_schema_entities(schema_blocks, page_url)

    # Images + alt & CLS dimensions audit
    images: list[dict] = []
    seen_imgs: set[str] = set()
    images_missing_alt = 0
    images_missing_dimensions = 0

    if og_image and og_image.startswith(("http://", "https://")):
        seen_imgs.add(og_image)
        images.append({"url": og_image, "alt": "Cover", "is_cover": True})

    for img in soup.find_all("img"):
        if (img.get("aria-hidden") or "").lower() == "true":
            continue
        best_src = _resolve_best_img_src(img, page_url)
        if not best_src:
            continue
        img["src"] = best_src
        alt_val = (img.get("alt") or "").strip()
        if not alt_val:
            images_missing_alt += 1
        if not img.get("width") or not img.get("height"):
            images_missing_dimensions += 1
        if best_src in seen_imgs:
            continue
        seen_imgs.add(best_src)
        images.append(
            {
                "url": best_src,
                "alt": alt_val[:160],
                "is_cover": False,
            }
        )

    resources = extract_resource_references(soup, page_url)
    if og_image and og_image not in {resource['url'] for resource in resources}:
        resources.append({'url': og_image, 'type': 'image', 'sourcePage': page_url,
                          'role': 'cover', 'label': 'Cover', 'language': None,
                          'mimeType': None, 'confidence': 'declared'})

    # Forms extraction (lead capture, newsletter, search, contact)
    forms: list[dict] = []
    for form in soup.find_all("form"):
        action = (form.get("action") or "").strip()
        method = (form.get("method") or "get").upper().strip()
        field_names: list[str] = []
        for inp in form.find_all(["input", "textarea", "select"]):
            itype = (inp.get("type") or inp.name or "text").lower()
            if itype in ("hidden", "submit", "button", "reset"):
                continue
            fname = (inp.get("name") or inp.get("placeholder") or inp.get("aria-label") or itype).strip()
            if fname and fname not in field_names:
                field_names.append(fname[:40])
        forms.append(
            {
                "action": urljoin(page_url, action) if action and not action.startswith("javascript:") else "",
                "method": method,
                "fields": field_names[:12],
            }
        )

    # Videos & Audio inventory
    videos: list[str] = []

    def _add_video(v_url: str) -> None:
        if v_url and v_url not in videos and len(videos) < 20:
            videos.append(v_url)

    for iframe in soup.find_all("iframe"):
        isrc = (iframe.get("src") or iframe.get("data-src") or "").strip()
        if isrc and any(k in isrc.lower() for k in ("youtube.com", "youtu.be", "vimeo.com", "loom.com", "wistia.")):
            _add_video(urljoin(page_url, isrc))
    for v_tag in soup.find_all("video"):
        vsrc = (v_tag.get("src") or "").strip()
        if vsrc:
            _add_video(urljoin(page_url, vsrc))
        for s_tag in v_tag.find_all("source"):
            if s_tag.get("src"):
                _add_video(urljoin(page_url, str(s_tag.get("src"))))

    # Links, contacts, downloads, CTAs, navigation, legal links, & generic anchor audit
    internal_links: list[dict] = []
    external_links: list[dict] = []
    emails: list[str] = []
    phones: list[str] = []
    downloads: list[dict] = []
    ctas: list[dict] = []
    seen_cta_labels: set[str] = set()
    header_nav: list[dict] = []
    seen_header_nav: set[str] = set()
    footer_links: list[dict] = []
    seen_footer_links: set[str] = set()
    legal_links: list[dict] = []
    seen_legal_types: set[str] = set()
    generic_anchors: list[dict] = []

    for a in soup.find_all("a", href=True):
        raw_href = (a.get("href") or "").strip()
        if not raw_href or raw_href.startswith(("#", "javascript:", "data:")):
            continue
        lower_href = raw_href.lower()
        if lower_href.startswith("mailto:"):
            addr = raw_href[7:].split("?", 1)[0].strip()
            if addr and addr not in emails:
                emails.append(addr)
            continue
        if lower_href.startswith("tel:"):
            num = raw_href[4:].split("?", 1)[0].strip()
            if num and num not in phones:
                phones.append(num)
            continue
        if lower_href.startswith("sms:"):
            continue
        full_href = urljoin(page_url, raw_href)
        parsed = urlparse(full_href)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            continue

        anchor_text = _clean_anchor_summary(a)
        anc_low = anchor_text.lower().strip()
        p_low = (parsed.path or "").lower()

        # Header vs Footer navigation structure
        in_header = a.find_parent(["header", "nav"]) is not None
        in_footer = a.find_parent("footer") is not None
        if in_header and not in_footer and anchor_text and len(anchor_text) <= 42:
            if full_href not in seen_header_nav and len(header_nav) < 18:
                seen_header_nav.add(full_href)
                header_nav.append({"label": anchor_text, "url": full_href})
        if in_footer and anchor_text and len(anchor_text) <= 48:
            if full_href not in seen_footer_links and len(footer_links) < 28:
                seen_footer_links.add(full_href)
                footer_links.append({"label": anchor_text, "url": full_href})

        # Legal & trust pages detection
        hay_legal = f"{p_low} {anc_low}"
        for legal_type, needles in _LEGAL_PATTERNS:
            if legal_type not in seen_legal_types and any(n in hay_legal for n in needles):
                seen_legal_types.add(legal_type)
                legal_links.append({"type": legal_type, "label": anchor_text or legal_type, "url": full_href})

        # CTA button detection
        a_classes = " ".join(a.get("class") or []).lower()
        a_role = (a.get("role") or "").lower()
        is_btn_styled = any(tok in a_classes for tok in ("btn", "button", "cta")) or a_role == "button"
        is_action_phrase = 2 <= len(anchor_text) <= 44 and _CTA_VERB_PREFIX_RE.search(anchor_text) is not None
        zone = "chrome" if _is_in_chrome_zone(a) else "body"
        if anchor_text and (is_btn_styled or (zone == "body" and is_action_phrase)):
            cta_key = anchor_text.lower()
            if cta_key not in seen_cta_labels and len(ctas) < 12:
                seen_cta_labels.add(cta_key)
                ctas.append({"label": anchor_text, "url": full_href, "zone": zone})

        # Track downloadable PDFs / lead magnets
        resource_type = classify_resource(full_href, declared_type=a.get('type'))['type']
        if a.has_attr('download') or resource_type == 'document':
            if all(d["url"] != full_href for d in downloads):
                downloads.append({"url": full_href, "label": anchor_text or os.path.basename(parsed.path)})

        # Track direct YouTube/Loom/Vimeo watch links
        h_low = (parsed.hostname or "").lower()
        if (
            ("youtube.com" in h_low and "/watch" in p_low)
            or h_low == "youtu.be"
            or ("loom.com" in h_low and "/share/" in p_low)
            or ("vimeo.com" in h_low and re.match(r"^/\d+", p_low))
        ):
            _add_video(full_href)

        rel_raw = a.get("rel") or []
        if isinstance(rel_raw, str):
            rel_list = [r.lower() for r in rel_raw.split() if r]
        else:
            rel_list = [str(r).lower() for r in rel_raw if r]

        if zone == "body" and anc_low in _GENERIC_ANCHORS and len(generic_anchors) < 15:
            generic_anchors.append({"anchor": anchor_text, "url": full_href})

        if is_same_site_host(parsed.hostname, target_host):
            norm_internal = canonicalize_crawl_url(full_href)
            if not norm_internal or resource_type != 'page' or a.has_attr('download'):
                continue
            internal_links.append(
                {
                    "url": norm_internal,
                    "anchor": anchor_text,
                    "rel": rel_list,
                    "zone": zone,
                }
            )
        else:
            ext_domain = canonicalize_external_domain(parsed.hostname)
            clean_ext = canonicalize_crawl_url(full_href) or full_href
            external_links.append(
                {
                    "url": clean_ext,
                    "domain": ext_domain,
                    "anchor": anchor_text,
                    "rel": rel_list,
                    "zone": zone,
                }
            )

    # Footer copyright & legal entity notice
    copyright_notice = ""
    footer_el = soup.find("footer")
    footer_text = re.sub(r"\s+", " ", footer_el.get_text(" ", strip=True)) if isinstance(footer_el, Tag) else ""
    if footer_text:
        cp_m = _COPYRIGHT_RE.search(footer_text)
        if cp_m:
            copyright_notice = cp_m.group(0).strip()[:120]

    # Published pricing & quantitative proof snippets (verbatim for grep-verifiable [FETCH] packs)
    pricing_mentions: list[str] = []
    proof_claims: list[str] = []
    main_scope = soup.find("main") or soup.body
    if isinstance(main_scope, Tag):
        for blk_el in main_scope.find_all(["p", "li", "h1", "h2", "h3", "td"]):
            if _is_in_chrome_zone(blk_el):
                continue
            txt_line = re.sub(r"\s+", " ", blk_el.get_text(" ", strip=True)).strip()
            if not (10 <= len(txt_line) <= 220):
                continue
            if _PRICE_SNIPPET_RE.search(txt_line) and txt_line not in pricing_mentions and len(pricing_mentions) < 8:
                pricing_mentions.append(txt_line)
            if _PROOF_CLAIM_RE.search(txt_line) and txt_line not in proof_claims and len(proof_claims) < 10:
                proof_claims.append(txt_line)

    # Full-fidelity semantic DOM-to-Markdown conversion (plus inline SVG chart capture)
    normalized_html = str(soup)
    inline_svgs: list[dict] = []
    markdown_body = convert_html_to_markdown(
        normalized_html,
        page_url,
        parser=_HTML_PARSER,
        inline_svgs_out=inline_svgs,
    )

    if len(markdown_body) < 40 and trafilatura is not None:
        try:
            extracted = trafilatura.extract(
                normalized_html,
                url=page_url,
                output_format="markdown",
                include_links=True,
                include_images=True,
                include_tables=True,
                favor_recall=True,
            )
            if extracted and len(extracted.strip()) > len(markdown_body):
                markdown_body = extracted.strip()
        except Exception:
            pass

    tables_count = len(soup.find_all("table"))
    code_blocks_count = len(soup.find_all("pre"))

    # Visible word & character count (excluding nav/header/footer/script/style)
    wc_soup = BeautifulSoup(html, _HTML_PARSER)
    for tag in wc_soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    visible_text = re.sub(r"\s+", " ", wc_soup.get_text(" ", strip=True)).strip()
    visible_chars = len(visible_text)
    words = re.findall(r"\b\w+\b", visible_text)
    word_count = len(words)
    reading_time_min = max(1, round(word_count / 220)) if word_count > 0 else 0
    content_hash = hashlib.sha256(markdown_body.encode("utf-8", errors="replace")).hexdigest()[:16]

    if not title:
        title = headings["h1"][0] if headings["h1"] else urlparse(page_url).path.strip("/") or "Home"

    # Canonical alignment check
    norm_self = canonicalize_crawl_url(page_url) or page_url
    norm_canon = canonicalize_crawl_url(canonical) if canonical else ""
    if not canonical:
        canonical_status = "missing"
    elif norm_canon == norm_self:
        canonical_status = "self"
    else:
        canonical_status = "other"

    social_card_complete = bool((og_title or title) and meta_description and og_image)

    # Per-page deterministic SEO audit checks
    seo_issues: list[str] = []
    if not soup.title or not soup.title.get_text(strip=True):
        seo_issues.append("missing-title")
    elif len(title) > 65:
        seo_issues.append("title-too-long")
    if not meta_description:
        seo_issues.append("missing-meta-description")
    elif len(meta_description) > 165:
        seo_issues.append("meta-description-too-long")
    if len(headings["h1"]) == 0:
        seo_issues.append("missing-h1")
    elif len(headings["h1"]) > 1:
        seo_issues.append("multiple-h1")
    if heading_level_skips > 0:
        seo_issues.append("heading-level-skip")
    if canonical_status == "missing":
        seo_issues.append("missing-canonical")
    elif canonical_status == "other":
        seo_issues.append("canonical-points-elsewhere")
    if "noindex" in meta_robots.lower():
        seo_issues.append("noindex")
    if "noindex" in x_robots_tag.lower():
        seo_issues.append("noindex-header")
    if "nofollow" in meta_robots.lower() or "nofollow" in x_robots_tag.lower():
        seo_issues.append("nofollow")
    if not soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}):
        seo_issues.append("missing-viewport")
    if jsonld_invalid:
        seo_issues.append(f"invalid-jsonld ({jsonld_invalid})")
    if hreflang_links and not any((canonicalize_crawl_url(h["url"]) or h["url"]) == norm_self for h in hreflang_links):
        seo_issues.append("hreflang-missing-self")
    if images_missing_alt > 0:
        seo_issues.append(f"images-missing-alt ({images_missing_alt})")
    if generic_anchors:
        seo_issues.append(f"generic-anchor-text ({len(generic_anchors)})")

    return {
        "title": title,
        "meta_description": meta_description,
        "meta_robots": meta_robots,
        "x_robots_tag": x_robots_tag,
        "canonical": canonical,
        "canonical_status": canonical_status,
        "lang": html_lang,
        "hreflang": hreflang_links,
        "author": author,
        "published_date": published_date,
        "modified_date": modified_date,
        "og_title": og_title,
        "og_image": og_image,
        "og_site_name": og_site_name,
        "og_type": og_type,
        "twitter_card": twitter_card,
        "twitter_site": twitter_site,
        "social_card_complete": social_card_complete,
        "theme_color": theme_color,
        "favicon": favicon,
        "rss_feeds": rss_feeds,
        "markdown_alternates": markdown_alternates,
        "h1": headings["h1"],
        "h2": headings["h2"],
        "h3": headings["h3"],
        "h4": headings["h4"],
        "heading_level_skips": heading_level_skips,
        "schema_types": schema_types,
        "schema_blocks": schema_blocks,
        "schema_entities": schema_entities,
        "emails": emails,
        "phones": phones,
        "forms": forms,
        "videos": videos,
        "resources": resources,
        "downloads": downloads,
        "ctas": ctas,
        "header_nav": header_nav,
        "footer_links": footer_links,
        "legal_links": legal_links,
        "copyright_notice": copyright_notice,
        "pricing_mentions": pricing_mentions,
        "proof_claims": proof_claims,
        "generic_anchors": generic_anchors,
        "tables_count": tables_count,
        "code_blocks_count": code_blocks_count,
        "word_count": word_count,
        "visible_chars": visible_chars,
        "reading_time_min": reading_time_min,
        "content_hash": content_hash,
        "images": images,
        "inline_svgs": inline_svgs,
        "images_missing_alt": images_missing_alt,
        "images_missing_dimensions": images_missing_dimensions,
        "seo_issues": seo_issues,
        "internal_links": internal_links,
        "external_links": external_links,
        "markdown": markdown_body,
    }


def sanitize_svg_bytes(raw: bytes) -> bytes:
    """Keep chart geometry while removing executable and remote SVG content."""
    from lxml import etree
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)', raw, re.I):
        raise ValueError("SVG declarations are not permitted")
    root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=False))
    if not isinstance(root.tag, str) or etree.QName(root).localname.lower() != "svg":
        raise ValueError("Not an SVG document")
    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            if element.getparent() is not None:
                element.getparent().remove(element)
            continue
        tag = etree.QName(element).localname.lower()
        if tag in {"script", "foreignobject", "iframe", "object", "embed", "style", "animate", "animatetransform", "set"}:
            if element.getparent() is not None:
                element.getparent().remove(element)
            continue
        for name, value in list(element.attrib.items()):
            local = etree.QName(name).localname.lower()
            unsafe = local.startswith("on") or local in {"src", "base"}
            if local == "href":
                unsafe = not value.startswith("#") and not (tag == "image" and re.match(r"^data:image/(?:png|jpeg|webp|gif);base64,", value, re.I))
            if local == "style" or "url(" in value.lower():
                unsafe = unsafe or bool(re.search(r"@import|expression\s*\(|url\(\s*['\"]?(?!#)", value, re.I))
            if unsafe:
                del element.attrib[name]
    return etree.tostring(root, encoding="utf-8")


class LocalAssetDownloader:
    """Single writer for bounded local image and sanitized inline SVG assets."""

    def __init__(self, assets_dir: str, max_images_total: int = 500, allow_url=None,
                 max_total_bytes: int = 128 * 1024 * 1024):
        self.assets_dir = assets_dir
        self.allow_url = allow_url
        self.max_images_total = max(0, max_images_total)
        self.max_total_bytes = max(0, max_total_bytes)
        self.cache: dict[str, Optional[str]] = {}
        self.bytes_by_file: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.downloaded_count = 0
        self.total_bytes = 0

    def _save_bytes(self, url: str, filename: str, raw: bytes) -> Optional[str]:
        if self.downloaded_count >= self.max_images_total:
            raise ValueError("Local image count limit reached")
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Image is empty or exceeds the per-file byte limit")
        if self.total_bytes + len(raw) > self.max_total_bytes:
            raise ValueError("Local image total byte limit reached")
        if os.path.basename(filename) != filename or filename in ("", ".", ".."):
            raise ValueError("Unsafe asset filename")
        os.makedirs(self.assets_dir, exist_ok=True)
        with open(os.path.join(self.assets_dir, filename), "wb") as file:
            file.write(raw)
        self.downloaded_count += 1
        self.total_bytes += len(raw)
        self.bytes_by_file[filename] = len(raw)
        self.cache[url] = filename
        return filename

    def save_inline_svg(self, pseudo_url: str, filename: str, svg_xml: str) -> Optional[str]:
        if pseudo_url in self.cache:
            return self.cache[pseudo_url]
        try:
            encoded = svg_xml.encode("utf-8")
            if len(encoded) > MAX_IMAGE_BYTES:
                raise ValueError("Inline SVG exceeds the per-file byte limit")
            raw = sanitize_svg_bytes(encoded)
            return self._save_bytes(pseudo_url, filename, raw)
        except Exception as exc:
            self.errors[pseudo_url] = str(exc)
            self.cache[pseudo_url] = None
            return None

    def save_download_result(self, url: str, result: dict) -> Optional[str]:
        """Write an already fetched image after applying all shared local budgets."""
        if url in self.cache:
            return self.cache[url]
        try:
            if result.get('error') or result.get('status_code') != 200:
                raise ValueError(result.get('error') or f"HTTP {result.get('status_code')}")
            raw = result.get('raw_bytes') or b''
            ctype = (result.get('content_type') or '').split(';', 1)[0].strip().lower()
            final_url = result.get('final_url') or url
            if classify_resource(final_url, ctype, result.get('content_disposition'))['type'] != 'image':
                raise ValueError("Response is not an image")
            if self.allow_url is not None and not self.allow_url(final_url):
                raise ValueError("Image refused by crawl policy")
            if not isinstance(raw, bytes) or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("Invalid image bytes or per-file byte limit reached")
            ext = _IMAGE_EXT_BY_MIME.get(ctype)
            if not ext:
                guessed = os.path.splitext(urlparse(final_url).path)[1].lower()
                ext = '.jpg' if guessed == '.jpeg' else guessed if guessed in ('.jpg', '.png', '.webp', '.gif', '.svg', '.avif', '.ico') else mimetypes.guess_extension(ctype) or '.img'
            if ext == '.svg':
                raw = sanitize_svg_bytes(raw)
            stem_raw = os.path.splitext(os.path.basename(urlparse(url).path))[0]
            clean_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem_raw).strip("-")[:40] or "img"
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
            filename = f"{clean_stem}-{digest}{ext}"
            return self._save_bytes(url, filename, raw)
        except Exception as exc:
            self.errors[url] = str(exc)
            self.cache[url] = None
            return None

    def download_image(self, img_url: str) -> Optional[str]:
        """Compatibility wrapper; parallel callers should fetch before the writer."""
        if img_url in self.cache:
            return self.cache[img_url]
        if self.downloaded_count >= self.max_images_total or self.total_bytes >= self.max_total_bytes:
            self.errors[img_url] = "Local image budget reached"
            self.cache[img_url] = None
            return None
        result = fetch_asset(img_url, self.allow_url, max_bytes=min(MAX_IMAGE_BYTES, self.max_total_bytes - self.total_bytes))
        return self.save_download_result(img_url, result)
