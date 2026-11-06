#!/usr/bin/env python3
"""Local graph heuristics, Bases views, byte receipts, drift and passive evidence.

Bases schema reference: https://obsidian.md/help/bases/syntax (2026-11-01).
The evidence pack is a passive record. It supplies observations
and explicit gaps, and makes no approval, tracking-delivery or brand verdict.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Optional
from urllib.parse import urlparse


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _yaml_q(value) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _cell(value) -> str:
    return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")


def compute_internal_pagerank(crawled_urls: list[str], internal_pair_meta: dict,
                              home_url: str, iterations: int = 25,
                              damping: float = 0.85) -> dict[str, int]:
    """Relative internal-link heuristic, not Google PageRank or SEO authority.

    Uniform teleportation and dangling redistribution; each distinct contextual
    edge weighs 1 and navigation-only edges weigh 0.22. Log scores are scaled
    across this capture to 0..100. A sole page has no relative comparison (50).
    Homepage identity does not alter the result.
    """
    urls = list(dict.fromkeys(crawled_urls))
    n = len(urls)
    if not n:
        return {}
    if not 0 < damping < 1 or iterations < 1:
        raise ValueError("PageRank needs damping between 0 and 1 and positive iterations")
    index = {url: i for i, url in enumerate(urls)}
    outgoing = [[] for _ in urls]
    totals = [0.0] * n
    for (source, target), meta in internal_pair_meta.items():
        if source not in index or target not in index or source == target:
            continue
        weight = 1.0 if "body" in meta.get("zones", ()) else 0.22
        outgoing[index[source]].append((index[target], weight))
        totals[index[source]] += weight
    ranks = [1 / n] * n
    for _ in range(iterations):
        dangling = sum(rank for rank, total in zip(ranks, totals) if not total)
        next_ranks = [(1 - damping + damping * dangling) / n] * n
        for source, edges in enumerate(outgoing):
            for target, weight in edges:
                next_ranks[target] += damping * ranks[source] * weight / totals[source]
        ranks = next_ranks
    values = [math.log1p(rank * n) for rank in ranks]
    span = max(values) - min(values)
    return {url: 50 if span < 1e-12 else int(round((values[i] - min(values)) / span * 100))
            for i, url in enumerate(urls)}


def build_pages_base_yaml(domain_folder: str, clean_domain: str,
                          captured_iso: Optional[str] = None) -> str:
    """JSON is also valid YAML; use structured filter objects without a dependency.

    Referenced note properties are emitted by the crawler. Limiting by capture
    timestamp prevents unvisited older notes from appearing as current evidence.
    """
    page_filter = 'note.kind != "external-domain"'
    common = ['file.ext == "md"', f'note.site == {json.dumps(clean_domain)}',
              {"or": [f'file.inFolder({json.dumps("sites/" + domain_folder + "/pages")})',
                      f'file.inFolder({json.dumps("sites/" + domain_folder + "/_external")})']}]
    if captured_iso:
        common.append(f'note.captured_at == {json.dumps(captured_iso)}')
    columns = ["file.name", "note.path", "note.health", "note.authority_score",
               "note.status_code", "note.response_time_ms", "note.click_depth",
               "note.in_sitemap", "note.word_count", "note.inlinks_body",
               "note.outlinks_body", "note.external_domains_count"]
    base = {
        "filters": {"and": common},
        "properties": {
            "note.authority_score": {"displayName": "Relative internal-link score"},
            "note.response_time_ms": {"displayName": "Final request duration (ms)"},
            "note.path": {"displayName": "URL path"},
            "note.health": {"displayName": "Recorded state"},
            "note.text_ratio": {"displayName": "Text to HTML (%)"},
            "note.readability": {"displayName": "Flesch reading ease"},
            "note.findings_count": {"displayName": "Findings"},
            "note.link_opportunities": {"displayName": "Link opportunities"},
        },
        "views": [
            {"type": "table", "name": "All Site Pages", "filters": page_filter,
             "order": columns, "sort": [{"property": "note.authority_score", "direction": "DESC"}],
             "summaries": {"note.word_count": "Sum", "note.inlinks_body": "Sum"}},
            {"type": "cards", "name": "Visual Cover Gallery", "filters": page_filter,
             "image": "note.cover", "imageFit": "contain",
             "order": ["file.name", "note.path", "note.health"]},
            {"type": "table", "name": "SEO Audit Queue", "filters": {"and": [page_filter,
                {"or": ['note.health == "orphan"', 'note.health == "unlisted"',
                        'note.health == "broken"', 'note.health == "redirect"',
                        "note.seo_issues_count > 0"]}]},
             "order": ["file.name", "note.path", "note.health", "note.seo_issues",
                       "note.images_missing_alt", "note.authority_score"]},
            {"type": "table", "name": "Top Hubs & Authority", "filters": page_filter,
             "order": ["file.name", "note.path", "note.kind", "note.authority_score",
                       "note.inlinks_body", "note.outlinks_body"],
             "sort": [{"property": "note.authority_score", "direction": "DESC"}]},
            {"type": "table", "name": "Content Quality", "filters": page_filter,
             "order": ["file.name", "note.path", "note.word_count", "note.text_ratio", "note.readability",
                       "note.duplicate", "note.dom_nodes", "note.findings_count"],
             "sort": [{"property": "note.findings_count", "direction": "DESC"}]},
            {"type": "table", "name": "Duplicates", "filters": {"and": [page_filter, "note.duplicate == true"]},
             "order": ["file.name", "note.path", "note.h1", "note.word_count", "note.content_hash"]},
            {"type": "table", "name": "Link Opportunities", "filters": {"and": [page_filter, "note.link_opportunities > 0"]},
             "order": ["file.name", "note.path", "note.link_opportunities", "note.outlinks_body", "note.inlinks_body"],
             "sort": [{"property": "note.link_opportunities", "direction": "DESC"}]},
            {"type": "table", "name": "Thin Pages", "filters": {"and": [page_filter, "note.word_count < 200", "note.words_measured != false", 'note.health != "broken"']},
             "order": ["file.name", "note.path", "note.word_count", "note.text_ratio", "note.inlinks_body"],
             "sort": [{"property": "note.word_count", "direction": "ASC"}]},
            {"type": "table", "name": "External Domains",
             "filters": 'note.kind == "external-domain"',
             "order": ["file.name", "note.domain", "note.linking_pages_count", "note.unique_urls_count"],
             "sort": [{"property": "note.linking_pages_count", "direction": "DESC"}]},
        ],
    }
    return json.dumps(base, indent=2, ensure_ascii=False) + "\n"


def _artifact(site_root: str, relative) -> Optional[Path]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        return None
    root = Path(site_root).resolve()
    raw = Path(relative)
    if raw.is_absolute() or any(part in ("", ".", "..") for part in raw.parts):
        return None
    path = root / raw
    try:
        if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
            return None
        return path
    except OSError:
        return None


def _text_source(site_root: str, row: dict):
    """Return UTF-8 text with its own byte identity and original-body anchor."""
    primary = _artifact(site_root, row.get("rawPath") or row.get("rawArtifact"))
    relative = row.get("textPath") or row.get("rawPath") or row.get("rawArtifact")
    path = _artifact(site_root, relative)
    if not primary or not path or path.stat().st_size > 5 * 1024 * 1024:
        return None, "Retained text artifact missing or exceeds 5 MB"
    data = path.read_bytes()
    if row.get("textPath"):
        expected = row.get("textSha256")
        if not isinstance(expected, str) or hashlib.sha256(data).hexdigest() != expected:
            return None, "Decoded text sidecar SHA-256 mismatch"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "Retained source is not UTF-8 and has no valid UTF-8 sidecar"
    kind = "decoded-text" if row.get("textPath") else row.get("rawKind", "unknown")
    return {"path": path, "relative": relative, "text": text, "rawKind": kind,
            "parentRawPath": row.get("rawPath"), "parentRawSha256": row.get("rawSha256")}, None


def _receipt(site_root: str, row: dict) -> dict:
    result = dict(row)
    relative = row.get("rawPath") or row.get("rawArtifact")
    path = _artifact(site_root, relative)
    expected = row.get("rawSha256")
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path and path.stat().st_size <= 5 * 1024 * 1024 else None
    verified = bool(actual and isinstance(expected, str) and actual == expected.lower())
    policy = row.get("robotsPolicy")
    policy_allowed = policy.get("allowed") is True if isinstance(policy, dict) else (
        isinstance(policy, str) and policy.startswith("allowed"))
    status = row.get("statusCode")
    size = path.stat().st_size if path else row.get("htmlBytes")
    visible = row.get("visibleChars")
    exclusions = []
    if not isinstance(status, int) or not 200 <= status < 300:
        exclusions.append("No successful 2xx page response")
    if row.get("redirectChain") or row.get("redirect_chain") or row.get("redirected"):
        exclusions.append("Redirected response")
    if not policy_allowed:
        exclusions.append("Robots policy refused or unavailable")
    if row.get("error"):
        exclusions.append("Fetch error")
    if not isinstance(size, int) or size > 5 * 1024 * 1024:
        exclusions.append("Missing byte size or response over 5 MB")
    if not isinstance(visible, int) or visible < 200:
        exclusions.append("HTML has fewer than 200 recorded visible characters")
    if not verified:
        exclusions.append("Retained bytes missing or SHA-256 mismatch")
    _text, text_error = _text_source(site_root, row)
    if text_error:
        exclusions.append(text_error)
    result.update({"rawPath": relative, "artifactSha256": actual,
                   "artifactVerified": verified, "dataEligible": not exclusions,
                   "dataState": "page evidence" if not exclusions else "no data",
                   "exclusions": exclusions,
                   "rawKind": row.get("rawKind") or ("rendered-dom" if row.get("renderUsed") else "http-response")})
    return result


def write_fetch_log(site_root: str, clean_domain: str, origin: str,
                    captured_iso: str, fetch_rows: list[dict]) -> dict:
    """Bind receipt rows to retained bytes and apply page-evidence gates."""
    rows = [_receipt(site_root, row) for row in fetch_rows]
    result = {"domain": clean_domain, "origin": origin, "capturedAt": captured_iso,
              "totalFetched": sum(row.get("attempted", True) is not False for row in rows),
              "totalRows": len(rows), "eligiblePages": sum(row["dataEligible"] for row in rows),
              "entries": rows}
    root = Path(site_root)
    _write_json(root / "_fetch-log.json", result)
    lines = [f"# Fetch Receipt Log: {clean_domain}", "",
             "HTTP-response bytes and rendered DOM bytes are distinct evidence classes.",
             "Response duration is not a measurement of time to first byte.", "",
             "| URL | HTTP | Duration | Bytes | Artifact | SHA-256 | Evidence class | Page data | Exclusions |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in (
            row.get("url") or row.get("path"), row.get("statusCode"), row.get("responseTimeMs"),
            row.get("htmlBytes"), row.get("rawPath"), row.get("rawSha256"), row["rawKind"],
            row["dataState"], "; ".join(row["exclusions"]))) + " |")
    (root / "_fetch-log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def _edge_keys(edges: list[dict], nodes: list[dict]) -> set[tuple]:
    identities = {node.get("id"): node.get("url") for node in nodes if node.get("kind") != "external-domain"}
    return {(identities.get(edge.get("source"), edge.get("source")),
             identities.get(edge.get("target"), edge.get("target")), edge.get("kind"), edge.get("targetUrl") or "")
            for edge in edges if isinstance(edge, dict)}


def compute_and_write_site_drift(site_root: str, clean_domain: str, captured_iso: str,
                                 prev_manifest: Optional[dict], new_internal_nodes: list[dict],
                                 new_ext_domains: list[str], *, new_edges: Optional[list[dict]] = None,
                                 capture_status: str = "partial", previous_site_root: Optional[str] = None,
                                 home_url: str = "", security_headers_present: Optional[list[str]] = None) -> Optional[dict]:
    """Compare observations. Absence from a crawl does not establish deletion."""
    if not prev_manifest or not isinstance(prev_manifest.get("nodes"), list):
        return None
    old_pages = {node["url"]: node for node in prev_manifest["nodes"]
                 if isinstance(node, dict) and node.get("url") and node.get("kind") != "external-domain"}
    current = {node["url"]: node for node in new_internal_nodes if node.get("url")}
    added = sorted(set(current) - set(old_pages))
    unobserved = sorted(set(old_pages) - set(current))
    confirmed_missing = sorted(url for url, node in current.items()
                               if url in old_pages and node.get("statusCode") in (404, 410))
    changes = {"titleChanges": [], "h1Changes": [], "healthChanges": [], "wordDeltas": [], "contentChanges": [],
               "descriptionChanges": [], "canonicalChanges": [], "noindexAdded": [], "noindexRemoved": [],
               "schemaChanges": [], "issueChanges": []}
    for url in sorted(set(old_pages) & set(current)):
        old, new = old_pages[url], current[url]
        body_observed = isinstance(new.get("statusCode"), int) and 200 <= new["statusCode"] < 300 and new.get("health") != "broken"
        for key, category in (("title", "titleChanges"), ("h1", "h1Changes")):
            if body_observed and old.get(key) != new.get(key):
                changes[category].append({"url": url, "old": old.get(key), "new": new.get(key)})
        if (old.get("statusCode"), old.get("health")) != (new.get("statusCode"), new.get("health")):
            changes["healthChanges"].append({"url": url, "oldStatus": old.get("statusCode"), "newStatus": new.get("statusCode")})
        delta = int(new.get("wordCount") or 0) - int(old.get("wordCount") or 0)
        # No word change where either capture did not measure words (languages written without spaces).
        measured = all((node.get("pageChecks") or {}).get("wordsMeasured") is not False for node in (old, new))
        if body_observed and measured and delta:
            changes["wordDeltas"].append({"url": url, "delta": delta})
        if body_observed and old.get("contentHash") and new.get("contentHash") and old["contentHash"] != new["contentHash"]:
            changes["contentChanges"].append({"url": url, "oldHash": old["contentHash"], "newHash": new["contentHash"]})
        if not body_observed:
            continue
        if (old.get("metaDescription") or "") != (new.get("metaDescription") or "") and "metaDescription" in old:
            changes["descriptionChanges"].append({"url": url, "old": old.get("metaDescription"), "new": new.get("metaDescription")})
        if (old.get("canonical") or "") != (new.get("canonical") or "") and "canonical" in old:
            changes["canonicalChanges"].append({"url": url, "old": old.get("canonical"), "new": new.get("canonical")})
        old_noindex = "noindex" in (old.get("metaRobots") or "").lower()
        new_noindex = "noindex" in (new.get("metaRobots") or "").lower()
        if new_noindex and not old_noindex:
            changes["noindexAdded"].append({"url": url, "old": old.get("metaRobots") or "", "new": new.get("metaRobots")})
        elif old_noindex and not new_noindex:
            changes["noindexRemoved"].append({"url": url, "old": old.get("metaRobots"), "new": new.get("metaRobots") or ""})
        old_schema, new_schema = set(old.get("schemaTypes") or []), set(new.get("schemaTypes") or [])
        if old_schema != new_schema:
            changes["schemaChanges"].append({"url": url, "added": sorted(new_schema - old_schema), "removed": sorted(old_schema - new_schema)})
        # 0.2.0 added many issue types; comparing against an older capture would list them all as new.
        if isinstance(old.get("seoIssues"), list) and tuple(int(x) for x in re.findall(r"\d+", str(prev_manifest.get("schemaVersion", "0")))[:3]) >= (1, 3, 0):
            strip = lambda items: {re.sub(r"\s*\(\d+\)$", "", i) for i in items or []}
            old_issues, new_issues = strip(old.get("seoIssues")), strip(new.get("seoIssues"))
            if old_issues != new_issues:
                changes["issueChanges"].append({"url": url, "added": sorted(new_issues - old_issues), "resolved": sorted(old_issues - new_issues)})
    old_external = {node["title"] for node in prev_manifest["nodes"] if isinstance(node, dict) and node.get("kind") == "external-domain" and isinstance(node.get("title"), str)}
    added_external = sorted(set(new_ext_domains) - old_external)
    absent_external = sorted(old_external - set(new_ext_domains))
    added_edges, absent_edges = [], []
    if new_edges is not None:
        previous_edges = _edge_keys(prev_manifest.get("edges") or [], prev_manifest["nodes"])
        current_edges = _edge_keys(new_edges, new_internal_nodes)
        added_edges = sorted(current_edges - previous_edges, key=str)
        absent_edges = sorted(previous_edges - current_edges, key=str)
    result = {"previousCapturedAt": prev_manifest.get("capturedAt"), "captureStatus": capture_status,
              "comparisonComplete": capture_status == "complete" and prev_manifest.get("captureStatus") == "complete",
              "addedPages": added, "unobservedPages": unobserved, "confirmedMissingPages": confirmed_missing,
              "removedPages": [], "removedPagesCount": 0, "addedPagesCount": len(added),
              "unobservedPagesCount": len(unobserved), "confirmedMissingPagesCount": len(confirmed_missing),
              **changes, **{name + "Count": len(rows) for name, rows in changes.items()},
              "addedExternalDomains": added_external, "unobservedExternalDomains": absent_external,
              "addedExternalDomainsCount": len(added_external), "removedExternalDomainsCount": 0,
              "addedEdges": added_edges, "unobservedEdges": absent_edges,
              "addedEdgesCount": len(added_edges), "unobservedEdgesCount": len(absent_edges)}
    file_changes = []
    if previous_site_root:
        import difflib
        for name in ("_raw/robots.txt", "llms.txt", "llms-full.txt", "security.txt"):
            old_file, new_file = Path(previous_site_root) / name, Path(site_root) / name
            if not old_file.is_file() and not new_file.is_file():
                continue
            old_lines = old_file.read_text(encoding="utf-8", errors="replace").splitlines() if old_file.is_file() else []
            new_lines = new_file.read_text(encoding="utf-8", errors="replace").splitlines() if new_file.is_file() else []
            if old_lines == new_lines:
                continue
            diff = list(difflib.unified_diff(old_lines, new_lines, "previous/" + name, "current/" + name, lineterm="", n=1))
            if diff:
                file_changes.append({"file": name.removeprefix("_raw/"), "added": sum(1 for d in diff if d.startswith("+") and not d.startswith("+++")),
                                     "removed": sum(1 for d in diff if d.startswith("-") and not d.startswith("---")), "diff": diff[:120]})
    header_changes = {}
    old_headers = (((prev_manifest.get("siteIntel") or {}).get("techStack") or {}).get("securityHeaders") or {}).get("present")
    if isinstance(old_headers, list) and security_headers_present is not None:
        header_changes = {"added": sorted(set(security_headers_present) - set(old_headers)),
                          "removed": sorted(set(old_headers) - set(security_headers_present))}
    result.update(fileChanges=file_changes, fileChangesCount=len(file_changes), headerChanges=header_changes, homeUrl=home_url)
    result["hasChanges"] = bool(added or confirmed_missing or added_external or added_edges or any(changes.values())
                                or file_changes or header_changes.get("added") or header_changes.get("removed"))
    root = Path(site_root)
    _write_json(root / "_drift-report.json", result)
    lines = [f"# Capture Drift: {clean_domain}", "",
             f"Compared {prev_manifest.get('capturedAt', 'unknown date')} to {captured_iso}.", "",
             "Missing inventory entries are unobserved, not proof that a page or link was removed.",
             f"Capture status: {capture_status}. Comparison complete: {str(result['comparisonComplete']).lower()}.", ""]
    sections = [("Newly observed pages", added), ("Previously observed pages not visited", unobserved),
                ("Fetched 404/410 responses", confirmed_missing), *changes.items(),
                ("Newly observed edges", added_edges), ("Previously observed edges absent from this snapshot", absent_edges)]
    for row in file_changes:
        lines.extend([f"## File changed: {row['file']}", "", "```diff", *row["diff"], "```", ""])
    if header_changes.get("added") or header_changes.get("removed"):
        lines.extend(["## Homepage security headers", "", f"- Added: {', '.join(header_changes['added']) or 'none'}",
                      f"- Removed: {', '.join(header_changes['removed']) or 'none'}", ""])
    for name, rows in sections:
        lines.extend([f"## {name}", ""])
        lines.extend("- " + (json.dumps(row, ensure_ascii=False) if not isinstance(row, str) else row) for row in rows)
        if not rows:
            lines.append("No observed changes in this category.")
        lines.append("")
    (root / "_drift-report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def _literal_observation(path: Path, relative: str, quote: str, label: str,
                         url: str, captured_iso: str, raw_kind: str, parent_raw=None) -> Optional[str]:
    if not quote or len(quote) > 700:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    index = text.find(quote)
    if index < 0:
        return None
    line = text[:index].count("\n") + 1
    # JSON-quoted strings preserve exact whitespace in a grep-verifiable form.
    escaped = json.dumps(quote, ensure_ascii=False)
    ticks = "`" * (max((len(match.group(0)) for match in re.finditer(r"`+", escaped)), default=0) + 1)
    anchor = f"; original body `{parent_raw[0]}` SHA-256 `{parent_raw[1]}`" if parent_raw else ""
    evidence_label = "RAW" if raw_kind == "supplied-html" else "FETCH"
    return f"- [{evidence_label}] {label}: {ticks}{escaped}{ticks}; locator `{relative}:{line}`; source `{url}`; captured `{captured_iso}`; class `{raw_kind}`{anchor}."


def write_evidence_pack(site_root: str, domain_folder: str, clean_domain: str,
                             brand_name: str, origin: str, captured_iso: str,
                             stack_intel: dict, brand_kit: dict, contacts: dict,
                             commercial_summary: dict, schema_Rollup: dict, *,
                             fetch_rows: Optional[list[dict]] = None,
                             page_records: Optional[list[dict]] = None,
                             capture_status: str = "partial") -> dict:
    """Produce passive evidence inputs from retained, hash-verified quoted spans.

    Derived stack labels and commercial summaries are intentionally not promoted
    into client facts without a retained source span. No approved Brand is created.
    """
    root = Path(site_root)
    if fetch_rows is None and (root / "_fetch-log.json").is_file():
        fetch_rows = json.loads((root / "_fetch-log.json").read_text(encoding="utf-8")).get("entries", [])
    receipts = write_fetch_log(site_root, clean_domain, origin, captured_iso, fetch_rows or [])["entries"]
    by_url = {row.get("url"): row for row in receipts}
    def record_receipt(record):
        requested = record.get("requestedUrl") or record.get("url")
        row = by_url.get(requested)
        if row and requested != record.get("url") and row.get("finalUrl") != record.get("url"):
            return None
        return row
    observations = []
    gaps = []
    for record in page_records or []:
        row = record_receipt(record)
        if not row or not row["dataEligible"]:
            gaps.append({"url": record.get("url"), "reason": (row or {}).get("exclusions") or ["No eligible retained page receipt"]})
            continue
        material, _error = _text_source(site_root, row)
        relative, path, text = material["relative"], material["path"], material["text"]
        parent_raw = (row["rawPath"], row["rawSha256"]) if row.get("textPath") else None
        spans = []
        for tag, label in (("title", "Title markup"), ("h1", "H1 markup")):
            for match in list(re.finditer(rf"<{tag}\b[^>]*>[\s\S]*?</{tag}\s*>", text, re.I))[:4]:
                spans.append((label, match.group(0)[:600]))
        for match in list(re.finditer(r"<meta\b[^>]*>", text, re.I))[:40]:
            if re.search(r'(?:name|property)\s*=\s*[\'"](?:description|og:site_name|og:title|og:description)[\'"]', match.group(0), re.I):
                spans.append(("Metadata markup", match.group(0)[:600]))
        for match in list(re.finditer(r"<a\b[^>]*href\s*=[^>]+>[\s\S]*?</a\s*>", text, re.I))[:12]:
            spans.append(("Published link markup", match.group(0)[:600]))
        for contact in (contacts.get("emails") or [])[:8] + (contacts.get("phones") or [])[:8]:
            if str(contact) in text:
                spans.append(("Published contact span", str(contact)))
        for label, quote in spans:
            observation = _literal_observation(path, relative, quote, label, record["url"], captured_iso, material["rawKind"], parent_raw)
            if observation and observation not in observations:
                observations.append(observation)
    design = []
    inferences = []
    typography = brand_kit.get("typography") or {}
    for token in ((brand_kit.get("palette") or []) + (brand_kit.get("colorTokens") or [])
                  + (typography.get("fontFaces") or []) + (typography.get("fontTokens") or [])
                  + (typography.get("fontStacks") or [])):
        relative = token.get("rawPath")
        path = _artifact(site_root, relative)
        quote = token.get("quote") or token.get("declared") or token.get("value")
        if not path or not token.get("rawSha256") or hashlib.sha256(path.read_bytes()).hexdigest() != token["rawSha256"]:
            continue
        parent_raw = None
        if token.get("rawKind") == "decoded-text":
            parent_path = _artifact(site_root, token.get("parentRawPath"))
            if not parent_path or hashlib.sha256(parent_path.read_bytes()).hexdigest() != token.get("parentRawSha256"):
                continue
            parent_raw = (token["parentRawPath"], token["parentRawSha256"])
        line = _literal_observation(path, relative, quote, f"CSS declaration at {token.get('selector', 'unknown selector')}", token.get("source", origin), captured_iso, token.get("rawKind", "retained-css-or-html"), parent_raw)
        if line:
            if line not in design:
                design.append(line)
            if token.get("candidateRole"):
                inferences.append(f"- [INFER] Candidate use `{token['candidateRole']}` from declaration {json.dumps(quote, ensure_ascii=False)}; locator `{relative}`; confidence `{token.get('confidence', 'low')}`. Requires a human design decision.")
    for row in receipts:
        if not row["dataEligible"] and not any(gap.get("url") == row.get("url") for gap in gaps):
            gaps.append({"url": row.get("url"), "reason": row["exclusions"]})
    export = {"captureStatus": capture_status, "observationsCount": len(observations),
              "designObservationsCount": len(design), "inferencesCount": len(inferences),
              "gaps": gaps, "source": "Web-Obs passive website evidence structure"}
    _write_json(root / "_evidence-pack.json", export)
    lines = [f"# Website Evidence Package: {clean_domain}", "",
             "## Assignment and coverage", "",
             "Passive local website observations for a separately chosen downstream project.",
             "This package performs no external action or human review and supplies no factual defaults.",
             "Full page and fetch coverage, policy decisions and exclusions are recorded in `_fetch-log.json`. Page spans are sampled: up to four title/H1 elements, 40 metadata tags and 12 anchors per eligible page; retained documents hold the full captured source.",
             "HTTP bytes and rendered DOM observations are labelled separately. No screenshots were inspected by this exporter.", "",
             "## Page records and source spans", "", *observations, "",
             "## Observed design declarations", "", *design, "",
             "## Proposed uses requiring human decisions", "", *inferences, "",
             "## Discovered CSS and logo references", "",
             "Discovery alone is not evidence of an approved Brand or a visually inspected asset.", ""]
    for declaration in brand_kit.get("resourceDeclarations") or []:
        path = _artifact(site_root, declaration.get("rawPath"))
        if not path or hashlib.sha256(path.read_bytes()).hexdigest() != declaration.get("rawSha256"):
            continue
        parent_raw = None
        if declaration.get("rawKind") == "decoded-text":
            parent_path = _artifact(site_root, declaration.get("parentRawPath"))
            if not parent_path or hashlib.sha256(parent_path.read_bytes()).hexdigest() != declaration.get("parentRawSha256"):
                continue
            parent_raw = (declaration["parentRawPath"], declaration["parentRawSha256"])
        line = _literal_observation(path, declaration["rawPath"], declaration.get("quote"),
                                    f"Discovered {declaration.get('kind', 'resource')} markup", origin,
                                    captured_iso, declaration.get("rawKind", "retained-html"), parent_raw)
        if line:
            lines.append(line)
    # Absolute resource references must themselves be found in retained HTML before export.
    references = set((brand_kit.get("stylesheetUrls") or []) + (brand_kit.get("logoUrls") or []))
    for reference in sorted(references):
        for record in page_records or []:
            row = record_receipt(record)
            if not row or not row["dataEligible"]:
                continue
            material, _error = _text_source(site_root, row)
            line = _literal_observation(material["path"], material["relative"], reference, "Discovered resource URL", record["url"], captured_iso, material["rawKind"], (row["rawPath"], row["rawSha256"]) if row.get("textPath") else None)
            if line:
                lines.append(line)
                break
    lines.extend(["", "## Missing evidence and unperformed decisions", ""])
    for gap in gaps:
        lines.append(f"- [INFER] No page observation exported for `{gap.get('url')}`; recorded exclusion {json.dumps(gap['reason'][0], ensure_ascii=False)}; locator `_fetch-log.json` (matching URL entry).")
    if not observations:
        lines.append("No eligible quoted page observations were available in this capture.")
    lines.extend(["", "Human decisions remain separate: approved brand roles, asset rights, commercial claim verification and the downstream project destination.", "",
                  "## Scope", "", "A passive record of what was observed. No review status or verdict is assigned.", ""])
    (root / "_evidence-pack.md").write_text("\n".join(lines), encoding="utf-8")
    return export
