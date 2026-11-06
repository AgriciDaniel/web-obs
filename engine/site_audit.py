"""Site-level audit built from one capture: duplicates, link graph, schema and file hygiene.

Pure functions over data the capture already holds. No network access. Every result
is an observation of the captured pages; uncaptured pages can change any of them.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlparse

from page_checks import STOPWORDS, significant_terms, simhash_distance, tokenize
from sitemap import url_match_key

MAX_TARGETS = 200
NEAR_DUPLICATE_BITS = 4  # SimHash Hamming distance treated as near duplicate
STALE_DAYS = 365
OVERSIZED_IMAGE_BYTES = 300 * 1024
HEAVY_IMAGE_BYTES = 1024 * 1024
GENERIC_ANCHORS = frozenset({"click here", "here", "read more", "learn more", "more", "this", "link", "details",
                             "see more", "view more", "continue", "continue reading", "go", "home", "next", "previous"})
_TITLE_SPLIT_RE = re.compile(r"\s+[|·:\-]\s+|\s+-\s+")
_SESSION_PARAM_RE = re.compile(r"(?:^|&)(?:sid|sessionid|session_id|phpsessid|jsessionid|sessid)=", re.I)
_CALENDAR_RE = re.compile(r"/(?:19|20)\d{2}/(?:0?[1-9]|1[0-2])(?:/|$)")
KNOWN_ROBOTS_DIRECTIVES = {"user-agent", "allow", "disallow", "sitemap", "crawl-delay", "host", "clean-param",
                           "content-signal", "request-rate", "visit-time", "noindex"}

# Google Search Central structured data requirements (required, recommended).
# A summary for orientation, not a substitute for the Rich Results Test.
SCHEMA_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "Article": ((), ("headline", "image", "datePublished", "author", "dateModified")),
    "NewsArticle": ((), ("headline", "image", "datePublished", "author", "dateModified")),
    "BlogPosting": ((), ("headline", "image", "datePublished", "author", "dateModified")),
    "Product": (("name",), ("image", "description", "offers|review|aggregateRating", "brand", "sku")),
    "Offer": (("price|priceSpecification", "priceCurrency|priceSpecification"), ("availability", "url")),
    "FAQPage": (("mainEntity",), ()),
    "BreadcrumbList": (("itemListElement",), ()),
    "Organization": ((), ("name", "url", "logo", "sameAs")),
    "LocalBusiness": (("name", "address"), ("telephone", "openingHoursSpecification|openingHours", "geo", "url")),
    "Event": (("name", "startDate", "location"), ("endDate", "image", "description", "offers", "eventStatus")),
    "Recipe": (("name", "image"), ("author", "datePublished", "recipeIngredient", "recipeInstructions")),
    "VideoObject": (("name", "thumbnailUrl", "uploadDate"), ("description", "duration", "contentUrl|embedUrl")),
    "JobPosting": (("title", "description", "datePosted", "hiringOrganization", "jobLocation|applicantLocationRequirements"),
                   ("validThrough", "employmentType", "baseSalary")),
    "SoftwareApplication": (("name", "offers", "aggregateRating|review"), ("applicationCategory", "operatingSystem")),
    "Review": (("itemReviewed", "author"), ("reviewRating",)),
    "WebSite": ((), ("name", "url")),
    "Person": ((), ("name", "url", "sameAs")),
}
LOCALBUSINESS_SUBTYPES = ("Restaurant", "Store", "Dentist", "Physician", "LegalService", "AutoRepair", "HomeAndConstructionBusiness",
                          "ProfessionalService", "FinancialService", "HealthAndBeautyBusiness", "LodgingBusiness")


def _finding(fid, category, tone, title, explanation, targets):
    unique, seen = [], set()
    for t in targets:
        key = (t.get("url"), t.get("sourceUrl"), t.get("detail"))
        if key not in seen:
            seen.add(key)
            unique.append(t)
    targets = unique
    return {"id": fid, "category": category, "tone": tone, "title": title, "explanation": explanation,
            "targets": targets[:MAX_TARGETS], "targetCount": len(targets)}


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u2019", "'").replace("\u2018", "'").strip().lower())


def _tok(value: str) -> str:
    return " ".join(tokenize(value))


def _key(url: str) -> str:
    return url_match_key(url) or url


def _token_string(text: str) -> str:
    return " " + " ".join(tokenize(text)) + " "


def _page_ok(node: dict) -> bool:
    return isinstance(node.get("statusCode"), int) and 200 <= node["statusCode"] < 300 and node.get("health") not in ("broken", "unavailable")


def _noindex(node: dict) -> bool:
    return "noindex" in (node.get("metaRobots") or "").lower() or "noindex" in (node.get("flags") or [])


def _parse_day(value) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text[:len(fmt) + 6].split(" GMT")[0].strip(), fmt).date()
        except ValueError:
            continue
    return None


def _strip_brand(title: str, brand: str) -> str:
    parts = [p.strip() for p in _TITLE_SPLIT_RE.split(title or "") if p.strip()]
    if len(parts) > 1 and brand:
        parts = [p for p in parts if _norm_text(p) != _norm_text(brand)] or parts
    return parts[0] if parts else (title or "")


# Duplicates

def _self_canonical(n: dict) -> bool:
    canon = n.get("canonical") or ""
    return not canon or _key(canon) == _key(n["url"])


def _words(n: dict) -> int:
    """The page's word count, or 0 where words are not measured (languages written without spaces)."""
    if (n.get("pageChecks") or {}).get("wordsMeasured") is False:
        return 0
    return n.get("wordCount") or 0


def find_duplicates(nodes: list[dict]) -> dict:
    # Pages that canonicalize elsewhere already name their preferred URL; the conflict checks cover them.
    ok = [n for n in nodes if _page_ok(n) and not _noindex(n) and _self_canonical(n)]

    def group(field):
        buckets = defaultdict(list)
        for n in ok:
            value = n.get(field)
            if isinstance(value, list):
                value = value[0] if value else ""
            value = _norm_text(value)
            if value:
                buckets[value].append(n["url"])
        return [{"value": v, "urls": sorted(urls)} for v, urls in sorted(buckets.items()) if len(urls) > 1]

    exact = defaultdict(list)
    for n in ok:
        if n.get("contentHash") and _words(n) >= 30:
            exact[n["contentHash"]].append(n["url"])
    exact_groups = [sorted(urls) for urls in exact.values() if len(urls) > 1]
    exact_members = {u for g in exact_groups for u in g}

    near = []
    hashed = [(n["url"], n["simhash"]) for n in ok
              if n.get("simhash") and _words(n) >= 80 and n["url"] not in exact_members]
    # All pairs: at most a few hundred thousand popcounts for the largest capture.
    for i, (url_a, value_a) in enumerate(hashed):
        for url_b, value_b in hashed[i + 1:]:
            distance = simhash_distance(value_a, value_b)
            if distance <= NEAR_DUPLICATE_BITS:
                near.append({"urls": sorted([url_a, url_b]), "similarity": round(1 - distance / 64, 3)})
    near.sort(key=lambda row: (-row["similarity"], row["urls"]))
    return {"titles": group("title"), "descriptions": group("metaDescription"), "h1": group("h1"),
            "exactContent": [{"urls": g} for g in exact_groups], "nearContent": near[:200],
            "note": "Compared across captured, indexable 2xx pages only."}


# Link graph

def internal_link_fixes(extracted_by_url: dict, nodes_by_url: dict, redirects: dict) -> list[dict]:
    rows = []
    seen = set()
    for src, ext in extracted_by_url.items():
        for link in ext.get("internal_links") or []:
            raw = link["url"]
            if (src, raw) in seen:
                continue
            seen.add((src, raw))
            final = redirects.get(raw)
            problem = None
            target = nodes_by_url.get(final or raw)
            if final and final != raw:
                problem = "redirect"
            elif target is not None and target.get("statusCode") in (404, 410):
                problem = "broken"
            elif target is not None and target.get("health") == "unavailable":
                problem = "unavailable"
            elif target is not None and target.get("canonical") and _key(target["canonical"]) != _key(target["url"]) and _page_ok(target):
                problem = "non-canonical"
            if problem:
                rows.append({"sourceUrl": src, "linkedUrl": raw, "targetUrl": final or (target or {}).get("canonical") or raw,
                             "problem": problem, "anchor": (link.get("anchor") or "")[:80], "zone": link.get("zone", "body")})
    order = {"broken": 0, "unavailable": 1, "redirect": 2, "non-canonical": 3}
    rows.sort(key=lambda r: (order[r["problem"]], r["linkedUrl"], r["sourceUrl"]))
    return rows[:2000]


def link_opportunities(nodes: list[dict], extracted_by_url: dict, linked_pairs: set, brand: str,
                       max_per_target: int = 8, max_total: int = 300) -> list[dict]:
    """Pages whose body text mentions another page's title or H1 phrase without linking to it."""
    ok = [n for n in nodes if _page_ok(n) and not _noindex(n) and n["url"] in extracted_by_url]
    texts = {n["url"]: _token_string(extracted_by_url[n["url"]].get("visible_text") or "") for n in ok}
    token_sets = {url: set(text.split()) for url, text in texts.items()}
    raw_texts = {n["url"]: extracted_by_url[n["url"]].get("visible_text") or "" for n in ok}
    phrase_pages = Counter()
    candidates = []
    for n in ok:
        phrases = set()
        for source in ([n["h1"][0]] if n.get("h1") else []) + [_strip_brand(n.get("title") or "", brand)]:
            toks = tokenize(source)
            if not (2 <= len(toks) <= 6):
                continue
            phrase = " ".join(toks)
            if len(phrase) < 12 or not [t for t in toks if t not in STOPWORDS and len(t) >= 3]:
                continue
            if brand and phrase == " ".join(tokenize(brand)):
                continue
            phrases.add(phrase)
        for phrase in phrases:
            candidates.append((n["url"], phrase))
    for _url, phrase in candidates:
        needle = f" {phrase} "
        words = set(phrase.split())
        phrase_pages[phrase] = sum(1 for u, text in texts.items() if words <= token_sets[u] and needle in text)
    limit = max(3, int(len(ok) * 0.3))
    results = []
    per_target = Counter()
    for target, phrase in sorted(candidates, key=lambda c: (-len(c[1]), c[0])):
        if phrase_pages[phrase] > limit:
            continue  # Boilerplate or a phrase too common to be a deliberate topic.
        needle = f" {phrase} "
        words = set(phrase.split())
        for src, text in texts.items():
            if src == target or (src, target) in linked_pairs or not words <= token_sets[src] or needle not in text:
                continue
            if per_target[target] >= max_per_target or len(results) >= max_total:
                break
            m = re.search(r"\b" + r"\W+".join(re.escape(t) for t in phrase.split()) + r"\b", raw_texts[src], re.I)
            context = ""
            if m:
                start, end = max(0, m.start() - 70), min(len(raw_texts[src]), m.end() + 70)
                context = ("..." if start else "") + raw_texts[src][start:end].strip() + ("..." if end < len(raw_texts[src]) else "")
            results.append({"sourceUrl": src, "targetUrl": target, "phrase": phrase, "context": context})
            per_target[target] += 1
    return results


def signal_conflicts(nodes: list[dict], nodes_by_url: dict, redirects: dict, extracted_by_url: dict) -> list[dict]:
    rows = []
    by_key = {_key(n["url"]): n for n in nodes}
    for n in nodes:
        if not _page_ok(n):
            continue
        canon = n.get("canonical") or ""
        canon_key = _key(canon) if canon else ""
        points_elsewhere = bool(canon) and canon_key != _key(n["url"])
        if points_elsewhere:
            target = by_key.get(canon_key) or nodes_by_url.get(redirects.get(canon, ""))
            if canon in redirects or (target is not None and target.get("health") == "redirect"):
                rows.append({"url": n["url"], "type": "canonical-to-redirect", "detail": f"Canonical {canon} redirects."})
            elif target is not None and isinstance(target.get("statusCode"), int) and target["statusCode"] >= 400:
                rows.append({"url": n["url"], "type": "canonical-to-error", "detail": f"Canonical {canon} returned HTTP {target['statusCode']}."})
            elif target is not None and _noindex(target):
                rows.append({"url": n["url"], "type": "canonical-to-noindex", "detail": f"Canonical {canon} is marked noindex."})
            elif target is not None and target.get("canonical") and _key(target["canonical"]) != canon_key:
                kind = "canonical-loop" if _key(target["canonical"]) == _key(n["url"]) else "canonical-chain"
                rows.append({"url": n["url"], "type": kind, "detail": f"Canonical {canon} declares its own canonical {target['canonical']}."})
            if _noindex(n):
                rows.append({"url": n["url"], "type": "noindex-and-canonical-elsewhere", "detail": "The page is noindex and also canonicalizes elsewhere; search engines may ignore one of the signals."})
            if n.get("inSitemap"):
                rows.append({"url": n["url"], "type": "sitemap-lists-non-canonical", "detail": f"Listed in the sitemap but canonicalizes to {canon}."})
            hreflang = (extracted_by_url.get(n["url"]) or {}).get("hreflang") or []
            if hreflang:
                rows.append({"url": n["url"], "type": "hreflang-on-canonicalized-page", "detail": "Declares hreflang alternates while canonicalizing to another URL."})
        if _noindex(n) and (n.get("inlinksBody") or 0) >= 5:
            rows.append({"url": n["url"], "type": "noindex-heavily-linked", "detail": f"{n['inlinksBody']} pages link to this noindex page from body content."})
    return rows


def weak_pages(nodes: list[dict], internal_pair_meta: dict, home_url: str) -> dict:
    single, dead, no_body, deep = [], [], [], []
    for n in nodes:
        if n["url"] == home_url or not _page_ok(n):
            continue
        if (n.get("inlinksTotal") or 0) == 1:
            single.append(n["url"])
        if (n.get("outlinksTotal") or 0) == 0:
            dead.append(n["url"])
        elif (n.get("outlinksBody") or 0) == 0 and _words(n) >= 300:
            no_body.append(n["url"])
        if isinstance(n.get("clickDepth"), int) and n["clickDepth"] > 3:
            deep.append({"url": n["url"], "clickDepth": n["clickDepth"]})
    nofollow = [{"sourceUrl": src, "targetUrl": dst} for (src, dst), meta in internal_pair_meta.items()
                if "nofollow" in (meta.get("rels") or set())]
    return {"singleInlink": sorted(single), "deadEnds": sorted(dead), "noBodyOutlinks": sorted(no_body),
            "deep": sorted(deep, key=lambda r: (-r["clickDepth"], r["url"])), "nofollowInternal": nofollow[:500]}


def cannibalization(nodes: list[dict], extracted_by_url: dict, brand: str) -> list[dict]:
    ok = [n for n in nodes if _page_ok(n) and not _noindex(n) and _self_canonical(n)]
    by_heading = defaultdict(list)
    by_focus = defaultdict(list)
    for n in ok:
        heading = (n.get("h1") or [""])[0] or _strip_brand(n.get("title") or "", brand)
        terms = tuple(sorted(set(significant_terms(heading)) - set(tokenize(brand))))
        if len(terms) >= 2:
            by_heading[terms].append(n["url"])
        kw = (extracted_by_url.get(n["url"]) or {}).get("keywords") or {}
        bigrams = kw.get("bigrams") or []
        title_tokens = " ".join(tokenize(n.get("title") or ""))
        brand_tokens = " ".join(tokenize(brand))
        if bigrams and bigrams[0]["density"] >= 1.0 and bigrams[0]["term"] in title_tokens and bigrams[0]["term"] not in brand_tokens:
            by_focus[bigrams[0]["term"]].append(n["url"])
    rows = [{"basis": "same-heading-terms", "term": " ".join(k), "urls": sorted(v)} for k, v in by_heading.items() if len(v) > 1]
    seen = {tuple(r["urls"]) for r in rows}
    rows += [{"basis": "same-focus-phrase", "term": k, "urls": sorted(v)} for k, v in by_focus.items()
             if len(v) > 1 and tuple(sorted(v)) not in seen]
    return sorted(rows, key=lambda r: (-len(r["urls"]), r["term"]))[:200]


def anchor_conflicts(internal_pair_meta: dict) -> list[dict]:
    targets = defaultdict(set)
    for (_src, dst), meta in internal_pair_meta.items():
        for anchor in meta.get("body_anchors") or []:
            a = _norm_text(anchor)
            if len(a) >= 4 and a not in GENERIC_ANCHORS:
                targets[a].add(dst)
    return sorted(({"anchor": a, "targets": sorted(t)} for a, t in targets.items() if len(t) > 1),
                  key=lambda r: (-len(r["targets"]), r["anchor"]))[:200]


def crawl_traps(extracted_by_url: dict) -> list[dict]:
    observed = set()
    for ext in extracted_by_url.values():
        for link in ext.get("internal_links") or []:
            observed.add(link["url"])
    variants = defaultdict(set)
    rows = []
    calendar, session, repeating, very_deep = [], [], [], []
    for url in observed:
        p = urlparse(url)
        if p.query:
            variants[p.path].add(p.query)
            if _SESSION_PARAM_RE.search(p.query):
                session.append(url)
        if _CALENDAR_RE.search(p.path):
            calendar.append(url)
        segs = [s for s in p.path.split("/") if s]
        if len(segs) > 8:
            very_deep.append(url)
        if len(segs) >= 4 and any(segs[i:i + 2] == segs[i + 2:i + 4] for i in range(len(segs) - 3)):
            repeating.append(url)
    for path, queries in variants.items():
        if len(queries) >= 10:
            params = Counter(k.split("=", 1)[0] for q in queries for k in q.split("&") if k)
            rows.append({"pattern": "query-variants", "path": path, "count": len(queries),
                         "parameters": [k for k, _ in params.most_common(6)]})
    if len(calendar) >= 20:
        rows.append({"pattern": "calendar-archive", "count": len(calendar), "sample": sorted(calendar)[:5]})
    if session:
        rows.append({"pattern": "session-ids-in-urls", "count": len(session), "sample": sorted(session)[:5]})
    if repeating:
        rows.append({"pattern": "repeating-path-segments", "count": len(repeating), "sample": sorted(repeating)[:5]})
    if very_deep:
        rows.append({"pattern": "very-deep-paths", "count": len(very_deep), "sample": sorted(very_deep)[:5]})
    return sorted(rows, key=lambda r: -r["count"])


# Content signals

def site_keywords(extracted_by_url: dict, top: int = 20) -> dict:
    out = {}
    for kind in ("unigrams", "bigrams", "trigrams"):
        counts, pages = Counter(), Counter()
        for ext in extracted_by_url.values():
            for row in (ext.get("keywords") or {}).get(kind) or []:
                counts[row["term"]] += row["count"]
                pages[row["term"]] += 1
        out[kind] = [{"term": t, "count": c, "pages": pages[t]} for t, c in counts.most_common() if pages[t] >= 2][:top]
    return out


def freshness(nodes: list[dict], captured_on: date) -> dict:
    stale, undated, dated = [], [], []
    for n in nodes:
        if not _page_ok(n):
            continue
        day = _parse_day(n.get("modifiedDate")) or _parse_day(n.get("publishedDate"))
        if day is None:
            undated.append(n["url"])
            continue
        age = (captured_on - day).days
        dated.append((day, n["url"]))
        if age > STALE_DAYS:
            stale.append({"url": n["url"], "date": day.isoformat(), "ageDays": age})
    dated.sort()
    return {"stale": sorted(stale, key=lambda r: -r["ageDays"])[:300], "undated": sorted(undated)[:300],
            "undatedCount": len(undated), "datedCount": len(dated), "staleAfterDays": STALE_DAYS,
            "oldest": {"url": dated[0][1], "date": dated[0][0].isoformat()} if dated else None,
            "newest": {"url": dated[-1][1], "date": dated[-1][0].isoformat()} if dated else None}


def trust_signals(nodes: list[dict], extracted_by_url: dict) -> dict:
    paths = {urlparse(n["url"]).path.lower().rstrip("/"): n["url"] for n in nodes if _page_ok(n)}

    def find(*needles):
        for path, url in sorted(paths.items(), key=lambda kv: len(kv[0])):
            last = path.rsplit("/", 1)[-1]
            if any(last == needle or last.startswith(needle + "-") or last.startswith(needle + ".") for needle in needles):
                return url
        return None
    legal_types = {}
    for ext in extracted_by_url.values():
        for row in ext.get("legal_links") or []:
            legal_types.setdefault(row["type"], row["url"])
    ok = [n for n in nodes if _page_ok(n)]
    return {
        "about": find("about", "about-us", "company", "who-we-are"),
        "contact": find("contact", "contact-us", "kontakt"),
        "privacy": legal_types.get("Privacy Policy") or find("privacy", "privacy-policy"),
        "terms": legal_types.get("Terms of Service") or find("terms", "terms-of-service", "terms-and-conditions"),
        "legalLinks": legal_types,
        "authorPages": sorted(u for p, u in paths.items() if re.search(r"/(author|authors|team|people)(/|$)", p))[:50],
        "pagesWithAuthor": sum(1 for n in ok if n.get("author")),
        "pagesWithDate": sum(1 for n in ok if n.get("publishedDate") or n.get("modifiedDate")),
        "pagesChecked": len(ok),
        "note": "Presence of pages and bylines only. Not an E-E-A-T judgement.",
    }


# Schema

def _types_of(item: dict) -> list[str]:
    t = item.get("@type")
    values = t if isinstance(t, list) else [t]
    return [v.rsplit("/", 1)[-1] for v in values if isinstance(v, str)]


def _has(item: dict, spec: str) -> bool:
    for key in spec.split("|"):
        value = item.get(key)
        if value not in (None, "", [], {}):
            return True
    return False


def _walk_schema(blocks: list) -> list[dict]:
    out, stack = [], list(blocks)
    while stack and len(out) < 200:
        item = stack.pop(0)
        if isinstance(item, list):
            stack.extend(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("@type"):
            out.append(item)
        for key, value in item.items():
            if key in ("offers", "mainEntity", "itemListElement", "@graph", "review", "hasPart") and isinstance(value, (dict, list)):
                stack.extend(value if isinstance(value, list) else [value])
    return out


def schema_eligibility(url: str, blocks: list, visible_text: str, page_path: str) -> tuple[list[dict], list[dict]]:
    eligibility, mismatches = [], []
    text = " " + _tok(visible_text) + " "
    seen = set()
    for item in _walk_schema(blocks):
        for stype in _types_of(item):
            rule_key = "LocalBusiness" if stype in LOCALBUSINESS_SUBTYPES else stype
            rule = SCHEMA_RULES.get(rule_key)
            if not rule:
                continue
            required, recommended = rule
            missing_req = [spec.replace("|", " or ") for spec in required if not _has(item, spec)]
            missing_rec = [spec.replace("|", " or ") for spec in recommended if not _has(item, spec)]
            if stype == "FAQPage":
                questions = item.get("mainEntity") or []
                questions = questions if isinstance(questions, list) else [questions]
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    answer = q.get("acceptedAnswer") or {}
                    if not q.get("name") or not (isinstance(answer, dict) and answer.get("text")):
                        missing_req.append("Question name and acceptedAnswer.text")
                        break
                for q in questions[:30]:
                    name = _tok(q.get("name") if isinstance(q, dict) else "")
                    if name and " " + name[:50].rsplit(" ", 1)[0] not in text:
                        mismatches.append({"url": url, "type": "FAQPage", "detail": f"Question not visible on the page: {name[:90]}"})
            if stype == "BreadcrumbList":
                parts = item.get("itemListElement") or []
                parts = parts if isinstance(parts, list) else [parts]
                if any(isinstance(p, dict) and not (p.get("position") and (p.get("name") or isinstance(p.get("item"), dict))) for p in parts):
                    missing_req.append("ListItem position and name")
                # Breadcrumbs may follow a user path rather than the URL (Google allows both), so no path check.
            if stype == "Product" and item.get("name"):
                name = _tok(str(item["name"]))
                if name and " " + name[:60].rsplit(" ", 1)[0] not in text:
                    mismatches.append({"url": url, "type": "Product", "detail": f"Product name not visible on the page: {name[:90]}"})
            if stype in ("Article", "NewsArticle", "BlogPosting") and isinstance(item.get("headline"), str):
                headline = _tok(item["headline"])
                if headline and " " + headline[:60].rsplit(" ", 1)[0] not in text:
                    mismatches.append({"url": url, "type": stype, "kind": "headline", "detail": f"Schema headline differs from the visible text: {item['headline'][:90]}"})
            key = (stype, tuple(missing_req), tuple(missing_rec))
            if key in seen:
                continue
            seen.add(key)
            eligibility.append({"url": url, "type": stype, "missingRequired": missing_req,
                                "missingRecommended": missing_rec, "eligible": not missing_req})
    return eligibility, mismatches


# Images, sitemap, robots

def image_weight(resources: list[dict]) -> dict:
    oversized, legacy = [], []
    for r in resources:
        if r.get("type") != "image":
            continue
        size = r.get("sourceBytes") or r.get("bytes") or 0
        mime = (r.get("mimeType") or "").lower()
        path = urlparse(r["url"]).path.lower()
        pages = sorted({ref["pageUrl"] for ref in r.get("references") or []})[:10]
        if size >= OVERSIZED_IMAGE_BYTES:
            oversized.append({"url": r["url"], "bytes": size, "pages": pages})
        fmt = ("bmp" if "bmp" in mime or path.endswith(".bmp") else "tiff" if "tiff" in mime or path.endswith((".tif", ".tiff"))
               else "png" if "png" in mime or path.endswith(".png") else "jpeg" if "jpeg" in mime or path.endswith((".jpg", ".jpeg"))
               else "gif" if "gif" in mime or path.endswith(".gif") else "")
        if fmt in ("bmp", "tiff") or (fmt in ("png", "jpeg", "gif") and size >= 100 * 1024):
            legacy.append({"url": r["url"], "format": fmt, "bytes": size, "pages": pages})
    return {"oversized": sorted(oversized, key=lambda r: -r["bytes"])[:200], "legacyFormats": sorted(legacy, key=lambda r: -r["bytes"])[:200],
            "thresholdBytes": OVERSIZED_IMAGE_BYTES, "note": "Sizes are the bytes the capture downloaded. Images not downloaded are not measured."}


def sitemap_limits(sitemaps_found: list[dict], conflicts: list[dict], origin_host: str, sitemap_urls: list[str]) -> dict:
    over_count = [row["url"] for row in sitemaps_found if (row.get("url_count") or 0) > 50000]
    over_size = [row["url"] for row in sitemaps_found if (row.get("bytes") or 0) > 50 * 1024 * 1024]
    foreign = sorted(u for u in sitemap_urls if (urlparse(u).hostname or "").lower().removeprefix("www.") != origin_host.removeprefix("www."))[:50]
    non_canonical = sorted({row["url"] for row in conflicts if row["type"] == "sitemap-lists-non-canonical"})
    return {"overUrlLimit": over_count, "overSizeLimit": over_size, "otherHostUrls": foreign,
            "nonCanonicalUrls": non_canonical[:200],
            "note": "Limits from sitemaps.org: 50,000 URLs and 50 MB uncompressed per file. Sizes are as transferred."}


def robots_syntax(robots_text: str) -> dict:
    issues = []
    in_group = False
    group_has_rule = True
    raw = (robots_text or "").lstrip("\ufeff")
    if len(raw.encode("utf-8", errors="replace")) > 500 * 1024:
        issues.append({"line": 0, "issue": "File is larger than Google's 500 KiB limit; rules after it are ignored."})
    for number, line in enumerate(raw.splitlines(), 1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        if ":" not in text:
            issues.append({"line": number, "issue": f"Line without a field name: {text[:80]}"})
            continue
        field, value = (part.strip() for part in text.split(":", 1))
        field_l = field.lower()
        if field_l not in KNOWN_ROBOTS_DIRECTIVES:
            issues.append({"line": number, "issue": f"Unknown directive '{field}'."})
            continue
        if field_l == "user-agent":
            if in_group and not group_has_rule:
                pass  # consecutive user-agent lines share one group
            in_group = True
            group_has_rule = False
        elif field_l in ("allow", "disallow", "crawl-delay", "noindex", "content-signal", "clean-param", "request-rate", "visit-time"):
            if not in_group:
                issues.append({"line": number, "issue": f"'{field}' appears before any User-agent line and is ignored."})
            group_has_rule = True
            if field_l == "noindex":
                issues.append({"line": number, "issue": "Noindex in robots.txt is not supported by Google since 2019."})
            if field_l == "crawl-delay":
                issues.append({"line": number, "issue": "Crawl-delay is ignored by Google; Bing and Yandex respect it."})
            if field_l in ("allow", "disallow") and value and not value.startswith(("/", "*")):
                issues.append({"line": number, "issue": f"Path should start with / or *: {value[:80]}"})
        elif field_l == "sitemap" and not value.lower().startswith(("http://", "https://")):
            issues.append({"line": number, "issue": f"Sitemap must be an absolute URL: {value[:80]}"})
    return {"issues": issues[:100], "issueCount": len(issues)}


def _luminance(hex6: str) -> float:
    channels = []
    for i in (0, 2, 4):
        c = int(hex6[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a.lstrip("#")[:6]), _luminance(b.lstrip("#")[:6])), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def palette_contrast(brand_kit: Optional[dict], limit: int = 8) -> dict:
    """WCAG contrast of observed palette colors. Roles are inferred, so this is a reference table, not a pass or fail."""
    colors = []
    for row in (brand_kit or {}).get("palette") or []:
        value = str(row.get("hex") or "").lower()
        if re.fullmatch(r"#[0-9a-f]{6}", value) and value not in colors:
            colors.append(value)
        if len(colors) >= limit:
            break
    rows = [{"color": c, "onWhite": contrast_ratio(c, "#ffffff"), "onBlack": contrast_ratio(c, "#000000")} for c in colors]
    pairs = []
    for i, a in enumerate(colors):
        for b in colors[i + 1:]:
            ratio = contrast_ratio(a, b)
            pairs.append({"a": a, "b": b, "ratio": ratio, "aaText": ratio >= 4.5, "aaLargeText": ratio >= 3.0, "aaaText": ratio >= 7.0})
    return {"colors": rows, "pairs": sorted(pairs, key=lambda p: -p["ratio"]),
            "note": "Palette roles are inferred from CSS, not observed text and background pairs. AA needs 4.5:1 for body text and 3:1 for large text. The axe-core browser sample checks real rendered contrast."}


def _page_target(url: str, detail: str = "", source: str = "") -> dict:
    row = {"url": url, "detail": re.sub(r"\s+", " ", str(detail or "")).strip()[:300]}
    if source:
        row["sourceUrl"] = source
    return row


def build_site_audit(*, nodes: list[dict], extracted_by_url: dict, internal_pair_meta: dict, redirects: dict,
                     home_url: str, origin: str, brand: str, resources: list[dict], sitemaps_found: list[dict],
                     sitemap_urls: list[str], robots_text: str, captured_iso: str, brand_kit: Optional[dict] = None) -> dict:
    nodes_by_url = {n["url"]: n for n in nodes}
    linked_pairs = set(internal_pair_meta)
    captured_on = date.fromisoformat(captured_iso[:10])
    duplicates = find_duplicates(nodes)
    fixes = internal_link_fixes(extracted_by_url, nodes_by_url, redirects)
    opportunities = link_opportunities(nodes, extracted_by_url, linked_pairs, brand)
    conflicts = signal_conflicts(nodes, nodes_by_url, redirects, extracted_by_url)
    weak = weak_pages(nodes, internal_pair_meta, home_url)
    cannibal = cannibalization(nodes, extracted_by_url, brand)
    anchors = anchor_conflicts(internal_pair_meta)
    traps = crawl_traps(extracted_by_url)
    fresh = freshness(nodes, captured_on)
    trust = trust_signals(nodes, extracted_by_url)
    eligibility, mismatches = [], []
    for url, ext in extracted_by_url.items():
        node = nodes_by_url.get(url)
        if node is None or not _page_ok(node):
            continue
        e, m = schema_eligibility(url, ext.get("schema_blocks") or [], ext.get("visible_text") or "", urlparse(url).path)
        eligibility.extend(e)
        mismatches.extend(m)
    images = image_weight(resources)
    host = (urlparse(origin).hostname or "").lower()
    smap = sitemap_limits(sitemaps_found, conflicts, host, sitemap_urls)
    robots = robots_syntax(robots_text)

    F = []
    for field, fid, label in (("titles", "dup-title", "title"), ("descriptions", "dup-description", "meta description"), ("h1", "dup-h1", "H1")):
        targets = [_page_target(u, f"Shared by {len(g['urls'])} pages: {g['value'][:80]}") for g in duplicates[field] for u in g["urls"]]
        if targets:
            F.append(_finding(fid, "content", "review", f"Pages share the same {label}",
                              f"Each group of pages uses one identical {label}. Distinct wording helps search engines and readers tell pages apart.", targets))
    targets = [_page_target(u, f"Identical body to {len(g['urls']) - 1} other page(s)") for g in duplicates["exactContent"] for u in g["urls"]]
    if targets:
        F.append(_finding("dup-content-exact", "content", "attention", "Pages have identical content",
                          "The extracted main content is byte-identical. Consolidate the pages or point a canonical at the preferred one.", targets))
    targets = [_page_target(row["urls"][0], f"{round(row['similarity'] * 100)}% similar to {row['urls'][1]}") for row in duplicates["nearContent"]]
    if targets:
        F.append(_finding("dup-content-near", "content", "review", "Pages are near duplicates",
                          "SimHash over the visible text found pages that differ only slightly. Templates with little unique text often show up here.", targets))
    labels = {"broken": "returns 404 or 410", "unavailable": "was unavailable", "redirect": "redirects", "non-canonical": "is not the canonical URL"}
    for problem, tone in (("broken", "attention"), ("unavailable", "coverage"), ("redirect", "review"), ("non-canonical", "review")):
        rows = [r for r in fixes if r["problem"] == problem]
        if rows:
            F.append(_finding(f"link-fix-{problem}", "links", tone, f"Internal links to a URL that {labels[problem]}",
                              "Update the link on the source page to point straight at the final, canonical URL.",
                              [_page_target(r["linkedUrl"], f"Linked from this page as \"{r['anchor'] or 'no text'}\". Use {r['targetUrl']}", r["sourceUrl"]) for r in rows]))
    if opportunities:
        F.append(_finding("link-opportunity", "links", "review", "Internal link opportunities",
                          "These pages mention another page's topic in their text but do not link to it. Heuristic: check that the mention really refers to that page.",
                          [_page_target(r["sourceUrl"], f"Mentions \"{r['phrase']}\": link to {r['targetUrl']}", r["sourceUrl"]) for r in opportunities]))
    conflict_titles = {
        "canonical-to-redirect": "Canonical points to a redirect", "canonical-to-error": "Canonical points to an error page",
        "canonical-to-noindex": "Canonical points to a noindex page", "canonical-chain": "Canonical chains",
        "canonical-loop": "Canonical loops", "noindex-and-canonical-elsewhere": "Noindex combined with a canonical elsewhere",
        "sitemap-lists-non-canonical": "Sitemap lists non-canonical URLs", "hreflang-on-canonicalized-page": "Hreflang on canonicalized pages",
        "noindex-heavily-linked": "Noindex pages with many internal links"}
    for ctype, title in conflict_titles.items():
        rows = [r for r in conflicts if r["type"] == ctype]
        if rows:
            tone = "attention" if ctype in ("canonical-to-error", "canonical-loop") else "review"
            F.append(_finding(f"conflict-{ctype}", "structure", tone, title,
                              "Two signals on these pages point in different directions. Search engines then pick one, which may not be the one you intend.",
                              [_page_target(r["url"], r["detail"]) for r in rows]))
    for key, fid, title, explanation in (
            ("singleInlink", "weak-single-inlink", "Pages with only one internal link pointing to them", "One route in makes a page easy to lose. Link to it from related pages."),
            ("deadEnds", "weak-dead-end", "Pages with no internal links out", "Visitors and crawlers stop here. Add links to related or parent pages."),
            ("noBodyOutlinks", "weak-no-body-links", "Long pages with no contextual links", "Only navigation links leave these pages. In-text links help readers and pass context."),
    ):
        if weak[key]:
            F.append(_finding(fid, "structure", "review", title, explanation, [_page_target(u) for u in weak[key]]))
    if weak["deep"]:
        F.append(_finding("weak-deep", "structure", "review", "Pages more than three clicks from the homepage",
                          "Deep pages are crawled less often. Link to them from a hub or the homepage.",
                          [_page_target(r["url"], f"Click depth {r['clickDepth']}") for r in weak["deep"]]))
    if weak["nofollowInternal"]:
        F.append(_finding("weak-nofollow-internal", "links", "review", "Internal links marked nofollow",
                          "Nofollow on your own links stops search engines from following them. It is rarely intended for internal pages.",
                          [_page_target(r["targetUrl"], "Linked with rel=nofollow", r["sourceUrl"]) for r in weak["nofollowInternal"]]))
    if cannibal:
        F.append(_finding("cannibalization", "content", "review", "Pages competing for the same topic",
                          "These pages share heading terms or a focus phrase. Merge them, or make each one target a distinct intent.",
                          [_page_target(u, f"Shares \"{row['term']}\" with {len(row['urls']) - 1} other page(s)") for row in cannibal for u in row["urls"]]))
    if anchors:
        F.append(_finding("anchor-multiple-targets", "links", "review", "One anchor text points to different pages",
                          "The same link text leads to different URLs. Readers and search engines expect one anchor to mean one destination.",
                          [_page_target(t, f"Anchor \"{row['anchor']}\" also points to {len(row['targets']) - 1} other page(s)") for row in anchors for t in row["targets"]]))
    if traps:
        F.append(_finding("crawl-traps", "structure", "review", "Possible crawl traps",
                          "URL patterns that can multiply without limit. Consider robots rules, canonicals or removing the links.",
                          [_page_target(row.get("path") or (row.get("sample") or [""])[0], f"{row['pattern']}: {row['count']} URLs") for row in traps]))
    if fresh["stale"]:
        F.append(_finding("stale-content", "content", "review", f"Pages not updated in over {STALE_DAYS} days",
                          "Based on the published or modified date the page declares. Review whether the content is still accurate.",
                          [_page_target(r["url"], f"Dated {r['date']} ({r['ageDays']} days)") for r in fresh["stale"]]))
    missing_trust = [label for label, key in (("About page", "about"), ("Contact page", "contact"), ("Privacy policy", "privacy"), ("Terms", "terms")) if not trust[key]]
    if missing_trust and home_url:
        F.append(_finding("trust-pages-missing", "content", "review", "Trust pages not found in the capture",
                          f"Not observed: {', '.join(missing_trust)}. They may exist outside the captured pages.", [_page_target(home_url, ", ".join(missing_trust))]))
    ineligible = [e for e in eligibility if not e["eligible"]]
    if ineligible:
        F.append(_finding("schema-missing-required", "schema", "review", "Structured data not eligible for its rich result",
                          "Google needs these properties before it can show that rich result. Ignore this when the rich result is not a goal. Based on Search Central documentation; confirm with the Rich Results Test.",
                          [_page_target(e["url"], f"{e['type']}: missing {', '.join(e['missingRequired'])}") for e in ineligible]))
    partial = [e for e in eligibility if e["eligible"] and e["missingRecommended"]]
    if partial:
        F.append(_finding("schema-missing-recommended", "schema", "review", "Structured data missing recommended properties",
                          "Optional properties that make a rich result more complete.",
                          [_page_target(e["url"], f"{e['type']}: add {', '.join(e['missingRecommended'])}") for e in partial]))
    hard = [m for m in mismatches if m.get("kind") != "headline"]
    soft = [m for m in mismatches if m.get("kind") == "headline"]
    if hard:
        F.append(_finding("schema-content-mismatch", "schema", "attention", "Structured data describes content that is not on the page",
                          "Markup must match what visitors can see. Hidden or mismatched markup can lose rich results.",
                          [_page_target(m["url"], m["detail"]) for m in hard]))
    if soft:
        F.append(_finding("schema-headline-differs", "schema", "review", "Article headline differs from the visible heading",
                          "The headline in the markup does not appear in the page text. Keep them aligned so search engines trust the markup.",
                          [_page_target(m["url"], m["detail"]) for m in soft]))
    if images["oversized"]:
        F.append(_finding("image-oversized", "images", "review", f"Images larger than {OVERSIZED_IMAGE_BYTES // 1024} KB",
                          "Large images slow pages down. Resize to the displayed size and compress.",
                          [_page_target(r["url"], f"{round(r['bytes'] / 1024)} KB", (r["pages"] or [""])[0]) for r in images["oversized"]]))
    if images["legacyFormats"]:
        F.append(_finding("image-legacy-format", "images", "review", "Images that could use a modern format",
                          "WebP or AVIF usually cut file size by a third or more at the same quality.",
                          [_page_target(r["url"], f"{r['format'].upper()}, {round(r['bytes'] / 1024)} KB", (r["pages"] or [""])[0]) for r in images["legacyFormats"]]))
    smap_targets = ([_page_target(u, "Over 50,000 URLs") for u in smap["overUrlLimit"]] + [_page_target(u, "Over 50 MB") for u in smap["overSizeLimit"]]
                    + [_page_target(u, "URL on another host") for u in smap["otherHostUrls"]])
    if smap_targets:
        F.append(_finding("sitemap-limits", "structure", "attention", "Sitemap limits or host problems",
                          "Search engines reject sitemap files over the limits and ignore URLs on other hosts.", smap_targets))
    if robots["issues"]:
        F.append(_finding("robots-syntax", "structure", "review", "robots.txt syntax notes",
                          "Lines that crawlers may ignore or read differently than intended.",
                          [{"url": origin.rstrip("/") + "/robots.txt", "detail": f"Line {i['line']}: {i['issue']}"} for i in robots["issues"]]))

    return {
        "version": 1,
        "duplicates": duplicates,
        "linkFixes": fixes,
        "linkOpportunities": opportunities,
        "conflicts": conflicts,
        "weakPages": weak,
        "cannibalization": cannibal,
        "anchorConflicts": anchors,
        "crawlTraps": traps,
        "keywords": site_keywords(extracted_by_url),
        "freshness": fresh,
        "trust": trust,
        "schema": {"eligibility": eligibility[:1000], "mismatches": mismatches[:500],
                   "note": "Summarized from Google Search Central structured data documentation. Not a Rich Results Test."},
        "images": images,
        "sitemapLimits": smap,
        "robotsSyntax": robots,
        "paletteContrast": palette_contrast(brand_kit),
        "findings": F,
    }
