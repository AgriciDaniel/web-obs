#!/usr/bin/env python3
"""
Main web-obs Website Intelligence & Obsidian Vault Generator CLI.

Pipeline:
1. Sitemap Discovery & Expansion (robots.txt, sitemapindex, urlset, .gz, feeds)
2. Page Crawl, Full-Fidelity Semantic Markdown, & Local Image / Inline SVG Saving
3. Internal & External Link Graph Topology + Site Analytics / Tech / AI Readiness:
   - sites/<domain>/pages/**/*.md (notes with YAML frontmatter, local images, wikilinks)
   - sites/<domain>/_external/*.md (external domain satellite notes)
   - sites/<domain>/_site-graph.json (structured 3D Site Globe + Site Intel manifest)
   - sites/<domain>/_site-summary.json (complete structured site & brand intelligence for downstream tools)
   - sites/<domain>/_sitemap.canvas (hierarchical Obsidian Canvas)
   - sites/<domain>/_pages.base (Obsidian Bases table)
   - sites/<domain>/_dashboard.md (Executive Site Overview, Tech Stack, AI/GEO, & SEO Audit)
"""

from __future__ import annotations

import sys as _sys

# Windows pipes default to the system code page. Events and notes are UTF-8.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import time
from typing import Optional
from urllib.parse import urlparse

if sys.version_info < (3, 14):
    print(json.dumps({"event": "error", "message": "Web-Obs requires Python 3.14 or newer."}), flush=True)
    raise SystemExit(1)

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from capture_store import CaptureTransaction
from evidence_export import (build_pages_base_yaml, compute_internal_pagerank,
    write_fetch_log, compute_and_write_site_drift, write_evidence_pack)
from brand_and_dns import extract_observed_brand_kit
from audit_outputs import (drift_findings, page_audit_section, page_findings, security_txt_findings,
    write_audit_report, write_findings_csv, write_tasks)
from issue_catalog import catalog_for_manifest
import page_checks
from site_audit import build_site_audit

from extractor import (  # noqa: E402
    LocalAssetDownloader,
    extract_page_data,
    fetch_page_html,
    is_crawlable_page_url,
)
from site_intel import (  # noqa: E402
    detect_analytics_and_stack,
    summarize_header_consistency,
    check_external_links,
    robots_url_decision,
    build_robots_policy,
    detect_funnel_platforms,
    is_clean_social_profile_url,
    probe_ai_and_discovery_endpoints,
)
from sitemap import (  # noqa: E402
    SitemapUrlEntry,
    _bounded_fetch_bytes,
    canonicalize_crawl_url,
    discover_and_expand_sitemaps,
    is_same_site_host,
    normalize_domain_host,
)


def emit_event(event_type: str, **payload) -> None:
    record = {"event": event_type, **payload}
    print(json.dumps(record, ensure_ascii=False), flush=True)


def sanitize_slug_segment(seg: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", seg).strip("-.")
    return cleaned[:72] or "page"


def url_to_vault_rel_note(url: str, domain_folder: str) -> tuple[str, str]:
    """
    Map a URL to a deterministic vault-relative Markdown path under sites/<domain>/pages/
    and return (vault_rel_path, section_slug).
    """
    parsed = urlparse(url)
    raw_segments = [s for s in (parsed.path or "/").split("/") if s]
    segments = [sanitize_slug_segment(s) for s in raw_segments]

    if parsed.query:
        q_hash = hashlib.sha256(parsed.query.encode("utf-8")).hexdigest()[:6]
        if segments:
            segments[-1] = f"{segments[-1]}-q-{q_hash}"
        else:
            segments = [f"index-q-{q_hash}"]

    if not segments:
        return f"sites/{domain_folder}/pages/index.md", "root"

    section = segments[0].lower()
    if len(segments) == 1:
        base = segments[0]
        if base.lower().endswith((".html", ".htm")):
            base = os.path.splitext(base)[0] or "page"
        return f"sites/{domain_folder}/pages/{base}.md", section

    folder_parts = segments[:-1]
    leaf = segments[-1]
    if leaf.lower().endswith((".html", ".htm")):
        leaf = os.path.splitext(leaf)[0] or "index"
    joined = "/".join(folder_parts + [f"{leaf}.md"])
    return f"sites/{domain_folder}/pages/{joined}", section


def _validation_summary(ai_intel: dict) -> str:
    parts = []
    for key, label in (("llmsTxt", "llms.txt"), ("securityTxt", "security.txt")):
        row = (ai_intel.get("validation") or {}).get(key)
        if row:
            parts.append(f"{label} {'valid' if row['valid'] else 'needs attention (' + ', '.join(row['issues']) + ')'}")
        elif ai_intel["endpoints"].get(key):
            parts.append(f"{label} not validated")
    return "; ".join(parts) if parts else "No llms.txt or security.txt to validate."


def _hygiene_summary(h: dict) -> str:
    counts = [(k, len(h.get(k) or [])) for k in ("broken", "unavailable", "redirect", "noindex", "undeclaredSitemaps", "lastmodMismatch", "hreflangNonReciprocal", "redirectChains")]
    issues = [f"{n} {k}" for k, n in counts if n]
    return ", ".join(issues) if issues else "No broken, redirected or noindex URLs listed in sitemaps."


def yaml_quote(val: Optional[str]) -> str:
    if val is None:
        return '""'
    text = str(val).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()
    return f'"{text}"'


def rewrite_markdown_for_obsidian(
    md_text: str,
    page_url: str,
    note_by_url: dict[str, str],
    url_aliases: dict[str, str],
    image_file_by_url: dict[str, Optional[str]],
    domain_folder: str,
) -> str:
    if not md_text:
        return ""

    # 1. Rewrite Markdown images ![alt](url) to local vault embeds ![[sites/<domain>/assets/file|alt]]
    img_pattern = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

    def _replace_img(match: re.Match) -> str:
        alt = match.group(1).strip().replace("|", "-").replace("\n", " ")
        raw_target = match.group(2).strip()
        local_name = image_file_by_url.get(raw_target)
        if local_name:
            asset_rel = f"sites/{domain_folder}/assets/{local_name}"
            return f"![[{asset_rel}|{alt}]]" if alt else f"![[{asset_rel}]]"
        if raw_target.startswith("inline-svg://"):
            return ""
        return match.group(0)

    rewritten = img_pattern.sub(_replace_img, md_text)

    # 2. Rewrite single-line inline Markdown links [text](url) when target is a crawled internal page note
    link_pattern = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

    def _replace_link(match: re.Match) -> str:
        raw_label = re.sub(r"\s+", " ", match.group(1)).strip().replace("|", "-")
        raw_href = match.group(2).strip()
        norm = canonicalize_crawl_url(raw_href)
        if norm:
            norm = url_aliases.get(norm, norm)
        if norm and norm in note_by_url and norm != page_url:
            target_note = note_by_url[norm][:-3] if note_by_url[norm].endswith(".md") else note_by_url[norm]
            return f"[[{target_note}|{raw_label}]]"
        return f"[{raw_label}]({raw_href})"

    return link_pattern.sub(_replace_link, rewritten)


_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)")
_MD_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\([^)\s]+\)")


def _md_label(text: str, limit: int = 90) -> str:
    """One-line link text that cannot break Markdown or a wikilink alias."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    clean = re.sub(r"\s*[\u2190-\u21ff\u2b00-\u2bff]+\s*$", "", clean)  # trailing arrows such as the external-link mark
    clean = clean.replace("[", "(").replace("]", ")").replace("|", "/")
    return clean[:limit].rstrip() + ("..." if len(clean) > limit else "")


def _human_bytes(size) -> str:
    if not isinstance(size, (int, float)) or size <= 0:
        return ""
    for unit, step in (("MB", 1024 * 1024), ("KB", 1024)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{int(size)} B"


def region_callout(region: dict, max_lines: int = 60) -> list[str]:
    """A site region (header, navigation, sidebar, footer) as a collapsed Obsidian callout.

    Remote images become their alt text, headings become bold lines so they stay out of the
    note outline, and lines that only repeat links already shown are dropped.
    """
    body = _MD_IMAGE_RE.sub(lambda m: m.group(1).strip(), region.get("markdown") or "")
    lines: list[str] = []
    seen: set[str] = set()
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line.lstrip().startswith("#"):
            line = "**" + line.lstrip().lstrip("#").strip() + "**"
        urls = [m.group(2) for m in _MD_LINK_RE.finditer(line)]
        rest = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", _MD_LINK_RE.sub("", line))
        if urls and all(u in seen for u in urls) and not re.search(r"[A-Za-z]{3,}", rest):
            continue
        seen.update(urls)
        lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return []
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["..."]
    return [f"> [!info]- {_md_label(region.get('label') or 'Site region', 60)}"] + [f"> {line}" if line else ">" for line in lines]


_RESOURCE_GROUPS = [("image", "Images"), ("video", "Video"), ("audio", "Audio"), ("transcript", "Captions and transcripts"),
                    ("document", "Documents"), ("stylesheet", "Stylesheets"), ("script", "Scripts"), ("font", "Fonts")]


def resource_label(resource: dict, page_url: str) -> str:
    """Alt text or link text when the page gave one, otherwise the file name, otherwise host and path."""
    refs = [r for r in resource.get("references") or [] if r.get("pageUrl") == page_url]
    generic = {"", resource.get("type") or "", "image", "font", "script", "stylesheet", "other", "document", "cover"}
    for ref in refs:
        label = _md_label(ref.get("label") or "")
        if label and label.lower() not in generic:
            return label
    parsed = urlparse(resource.get("url") or "")
    name = os.path.basename(parsed.path.rstrip("/"))
    if name:
        return _md_label(name, 70)
    return _md_label(f"{parsed.hostname or ''}{parsed.path or ''}", 70) or "resource"


def media_section(page_resources: list[dict], page_url: str) -> list[str]:
    groups: dict[str, list[dict]] = {}
    for resource in page_resources:
        groups.setdefault(resource.get("type") or "other", []).append(resource)
    order = [key for key, _ in _RESOURCE_GROUPS] + sorted(k for k in groups if k not in dict(_RESOURCE_GROUPS))
    titles = dict(_RESOURCE_GROUPS)
    lines = ["## Media and Resources", ""]
    for key in order:
        rows = groups.get(key)
        if not rows:
            continue
        lines.append(f"**{titles.get(key, key.replace('-', ' ').capitalize())}** ({len(rows)})")
        for resource in rows:
            label = resource_label(resource, page_url)
            target = f"[[{resource['localPath']}|{label}]]" if resource.get("localPath") else f"[{label}]({resource['url']})"
            extras = [_human_bytes(resource.get("bytes") or resource.get("sourceBytes"))]
            status = resource.get("checkStatus")
            if status and status not in ("ok", "unchecked"):
                extras.append(status)
            host = urlparse(resource.get("url") or "").hostname or ""
            page_host = urlparse(page_url).hostname or ""
            if host and host != page_host:
                extras.append(host)
            suffix = " · ".join(x for x in extras if x)
            lines.append(f"- {target}" + (f" · {suffix}" if suffix else ""))
        lines.append("")
    return lines


def property_table(rows: list[tuple[str, str]]) -> list[str]:
    out = ["| Property | Value |", "| :--- | :--- |"]
    for label, value in rows:
        if value not in (None, ""):
            out.append(f"| {label} | {str(value).replace('|', '/')} |")
    return out


def infer_brand_name(home_ext: Optional[dict], clean_domain: str) -> str:
    if home_ext:
        og_site = (home_ext.get("og_site_name") or "").strip()
        if og_site:
            return og_site
        for blk in home_ext.get("schema_blocks") or []:
            btype = blk.get("@type")
            types = btype if isinstance(btype, list) else [btype]
            if any(t in ("WebSite", "Organization", "LocalBusiness", "Brand", "SoftwareApplication") for t in types):
                nm = (blk.get("name") or "").strip()
                if nm and len(nm) <= 50:
                    return nm
        title = (home_ext.get("title") or "").strip()
        for sep in (" | ", " - ", ": "):
            if sep in title:
                cand = title.split(sep)[0].strip()
                if 2 <= len(cand) <= 42:
                    return cand
    return clean_domain


def ensure_obsidian_graph_colors(vault_dir: str) -> None:
    """Configure .obsidian/graph.json color groups for native 2D Obsidian Graph View (with backup)."""
    obs_dir = os.path.join(vault_dir, ".obsidian")
    if not os.path.isdir(obs_dir):
        return
    graph_path = os.path.join(obs_dir, "graph.json")
    desired_groups = [
        {"query": "tag:#web-obs/home", "color": {"a": 1, "rgb": 2450411}},
        {"query": "tag:#web-obs/hub", "color": {"a": 1, "rgb": 890034}},
        {"query": "tag:#web-obs/orphan", "color": {"a": 1, "rgb": 14251782}},
        {"query": "tag:#web-obs/broken OR tag:#web-obs/redirect", "color": {"a": 1, "rgb": 14427686}},
        {"query": "tag:#web-obs/external", "color": {"a": 1, "rgb": 8145645}},
        {"query": "tag:#web-obs/page", "color": {"a": 1, "rgb": 3368559}},
    ]
    existing = {}
    if os.path.isfile(graph_path):
        backup_path = f"{graph_path}.bak"
        if not os.path.isfile(backup_path):
            shutil.copy2(graph_path, backup_path)
        try:
            with open(graph_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    existing["colorGroups"] = desired_groups
    existing.setdefault("showArrow", True)
    existing.setdefault("showOrphans", True)
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def generate_sitemap_canvas(
    nodes: list[dict],
    edges: list[dict],
) -> dict:
    """Retain all internal pages and eligible relationships in the Canvas export."""
    internal_nodes = [n for n in nodes if n["kind"] != "external-domain"]
    by_depth: dict[int, list[dict]] = {}
    for n in internal_nodes:
        d = n["clickDepth"] if n["clickDepth"] is not None else 4
        d_clamped = min(4, max(0, d))
        by_depth.setdefault(d_clamped, []).append(n)

    canvas_nodes: list[dict] = []
    canvas_edges: list[dict] = []
    included_ids: set[str] = set()

    col_width = 430
    card_w = 310
    card_h = 110
    row_gap = 140

    color_by_health = {
        "home": "5",
        "hub": "4",
        "healthy": "6",
        "orphan": "2",
        "unlisted": "3",
        "redirect": "1",
        "broken": "1",
        "unavailable": "3",
    }

    for depth in sorted(by_depth.keys()):
        col_items = sorted(by_depth[depth], key=lambda item: (item["section"], item["url"]))
        total_h = len(col_items) * row_gap
        start_y = -total_h // 2
        for idx, n in enumerate(col_items):
            included_ids.add(n["id"])
            canvas_nodes.append(
                {
                    "id": n["id"],
                    "type": "file",
                    "file": n["obsidianPath"],
                    "x": depth * col_width,
                    "y": start_y + idx * row_gap,
                    "width": card_w,
                    "height": card_h,
                    "color": color_by_health.get(n["health"], "6"),
                }
            )

    seen_edge_ids: set[str] = set()
    for e in edges:
        if e["kind"] not in ("sitemap-hierarchy", "internal-body"):
            continue
        s, t = e["source"], e["target"]
        if s in included_ids and t in included_ids and e["id"] not in seen_edge_ids:
            seen_edge_ids.add(e["id"])
            canvas_edges.append(
                {
                    "id": e["id"],
                    "fromNode": s,
                    "fromSide": "right",
                    "toNode": t,
                    "toSide": "left",
                }
            )

    return {"nodes": canvas_nodes, "edges": canvas_edges}


def _capture_to_staging(
    target_url: str,
    vault_dir: str,
    max_pages: int = 250,
    download_images: bool = True,
    render_mode: str = "auto",
    delay_sec: float = 0.15,
    previous_vault_dir: Optional[str] = None,
    check_external: bool = True,
    parallel: bool = True,
    image_mode: str = "preferred",
    browser_audit: bool = True,
    spell_check: bool = False,
    dns_checks: bool = True,
    snapshot_limit: int = 25,
    snapshot_html: bool = False,
    tls_check: bool = True,
    tasks: bool = True,
    deadline_sec: Optional[float] = None,
) -> dict:
    started_at = time.time()
    page_checks.configure(spell_check=spell_check)
    from provenance import capture_provenance, assert_engine_unchanged
    provenance = capture_provenance({"maxPages": max_pages, "downloadImages": download_images,
        "imageMode": image_mode, "renderMode": render_mode, "delaySec": delay_sec,
        "checkExternal": check_external, "parallel": parallel,
        "browserAudit": browser_audit, "spellCheck": spell_check, "dnsChecks": dns_checks,
        "snapshotLimit": snapshot_limit, "snapshotHtml": snapshot_html,
        "tlsCheck": tls_check, "tasks": tasks, "deadlineSec": deadline_sec,
        "limits": {"assets": 500, "assetBytes": 128 * 1024 * 1024, "linkChecks": 1000, "linkDrainSeconds": 30}})
    emit_event("start", target=target_url, maxPages=max_pages)

    # STEP 1: SITEMAP FIRST
    emit_event("phase", phase="sitemap", message="Discovering robots.txt and expanding sitemaps...")
    sm_result = discover_and_expand_sitemaps(
        target_url,
        on_progress=lambda sm_url, sm_cnt, url_cnt: emit_event(
            "sitemap_progress",
            sitemapUrl=sm_url,
            sitemapsFound=sm_cnt,
            urlsDiscovered=url_cnt,
        ),
    )

    origin = sm_result.origin
    parsed_origin = urlparse(origin)
    target_host = parsed_origin.hostname or ""
    clean_domain = normalize_domain_host(target_host)
    if parsed_origin.port and parsed_origin.port not in (80, 443):
        domain_folder = f"{clean_domain}-{parsed_origin.port}"
    else:
        domain_folder = clean_domain

    if ":" in domain_folder:
        domain_folder = "ip6-" + hashlib.sha256(domain_folder.encode()).hexdigest()[:20]
    else:
        domain_folder = domain_folder.encode("idna").decode("ascii")
    site_root = os.path.join(vault_dir, "sites", domain_folder)
    pages_dir = os.path.join(site_root, "pages")
    ext_dir = os.path.join(site_root, "_external")
    assets_dir = os.path.join(site_root, "assets")
    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(ext_dir, exist_ok=True)
    previous_manifest = None
    if previous_vault_dir:
        previous_path = os.path.join(previous_vault_dir, "sites", domain_folder, "_site-graph.json")
        if os.path.isfile(previous_path):
            with open(previous_path, encoding="utf-8") as f:
                previous_manifest = json.load(f)
    fetch_rows: list[dict] = []
    page_records: list[dict] = []
    source_artifacts: dict = {}
    raw_dir = os.path.join(site_root, "_raw")
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(sm_result.robots_text)
    robots_policy = sm_result.robots_policy
    robots_policies = {origin: robots_policy}
    def policy_for(url):
        parsed = urlparse(url)
        resource_origin = f"{parsed.scheme}://{parsed.netloc}"
        if resource_origin not in robots_policies:
            evidence = _bounded_fetch_bytes(resource_origin + "/robots.txt", max_bytes=1024 * 1024)
            raw = evidence.get("content") or b""
            policy = build_robots_policy(raw.decode("utf-8-sig", errors="replace"), evidence.get("status_code"), evidence.get("error"), evidence.get("too_large", False))
            robots_policies[resource_origin] = policy
            from url_safety import apply_robots_pacing
            apply_robots_pacing(resource_origin, policy)
            digest = hashlib.sha256(raw).hexdigest()
            with open(os.path.join(raw_dir, f"robots-{digest}.txt"), "wb") as f:
                f.write(raw)
        return robots_policies[resource_origin]
    def allow_resource(url):
        return not is_same_site_host(urlparse(url).hostname or "", target_host) or robots_url_decision(policy_for(url), url)["allowed"]
    def allow_page(url):
        return is_same_site_host(urlparse(url).hostname or "", target_host) and allow_resource(url)

    home_url = canonicalize_crawl_url(f"{origin}/") or f"{origin}/"
    sitemap_urls: dict[str, SitemapUrlEntry] = dict(sm_result.entries)

    emit_event(
        "sitemap_done",
        sitemapsCount=len(sm_result.sitemaps_found),
        sitemapUrlsCount=len(sitemap_urls),
    )

    from pipeline import collect_site
    emit_event("phase", phase="crawl", message="Collecting pages, media and link checks in bounded queues...")
    collected = collect_site(origin, target_url, target_host, sitemap_urls,
        site_root, domain_folder, max_pages, download_images, render_mode,
        delay_sec, robots_policies, policy_for, allow_resource, emit_event,
        check_external=check_external, parallel=parallel, image_mode=image_mode, extract_fn=extract_page_data)
    crawled_pages = collected["pages"]
    fetch_redirects = collected["aliases"]
    link_form_mismatches = collected.get("link_form_mismatches") or {}
    url_aliases = {**collected.get("form_aliases", {}), **fetch_redirects}
    image_file_by_url = collected["images"]
    html_samples = collected["html_samples"]
    home_headers = collected["home_headers"]
    fetch_rows = collected["fetch_rows"]
    page_records = collected["page_records"]
    source_artifacts = collected["source_artifacts"]
    downloader = collected["downloader"]
    resources = collected["resources"]
    with open(os.path.join(site_root, "_robots-receipts.json"), "w", encoding="utf-8") as f:
        json.dump(collected["robots_receipts"], f, indent=2, ensure_ascii=False)
    capture_warnings = list(sm_result.warnings) + collected["warnings"]
    capture_findings = list(collected.get("findings") or [])
    # "partial" means pages or resources were not collected. A 404 the capture found is a finding.
    capture_status = "partial" if capture_warnings else "complete"

    if home_url in url_aliases and url_aliases[home_url] in crawled_pages:
        home_url = url_aliases[home_url]
    elif home_url not in crawled_pages and crawled_pages:
        home_url = next(iter(crawled_pages.keys()))

    # STEP 3: SITE INTELLIGENCE, LINK TOPOLOGY, & OBSIDIAN VAULT COMPILATION
    emit_event(
        "phase",
        phase="compile",
        message="Analyzing tech stack, AI readiness, link graph, and writing Obsidian vault...",
    )

    home_ext = (crawled_pages.get(home_url) or {}).get("extracted")
    brand_name = infer_brand_name(home_ext, clean_domain)

    # Read published discovery files and inspect captured HTML locally.
    stack_intel = detect_analytics_and_stack(html_samples, home_headers)
    stack_intel["coverage"] = {"sampledPages": len(html_samples),
        "capturedHtmlPages": sum(bool(p.get("extracted")) for p in crawled_pages.values()),
        "sourceUrls": collected["sample_urls"],
        "selection": "Homepage first, then URL order; at most eight HTML pages",
        "securityHeadersScope": "Homepage response, with consistency checked across sampled pages"}
    stack_intel["securityHeaders"]["consistency"] = summarize_header_consistency(collected.get("sample_headers") or {})
    ai_intel = probe_ai_and_discovery_endpoints(origin, site_root, sm_result.robots_text, html_samples, robots_policy)

    # Sitemap hygiene: listed URLs that are broken, redirected or noindex, and sitemaps robots.txt does not declare.
    hygiene = {"broken": [], "unavailable": [], "redirect": [], "noindex": [], "undeclaredSitemaps": []}
    for page_url, page in crawled_pages.items():
        if not page.get("in_sitemap"):
            continue
        code = page.get("status_code") or 0
        meta_robots = ((page.get("extracted") or {}).get("meta_robots") or "").lower()
        if code in (404, 410):
            hygiene["broken"].append(page_url)
        elif code >= 400 or code == 0 or page.get("error"):
            hygiene["unavailable"].append(page_url)
        elif page.get("redirect_chain") and page_url != home_url:
            hygiene["redirect"].append(page_url)
        elif "noindex" in meta_robots:
            hygiene["noindex"].append(page_url)
    # A sitemap URL that redirects elsewhere is reported even when its destination was also
    # crawled directly (the crawl keeps one record per destination).
    for source_url, destination_url in fetch_redirects.items():
        if source_url != destination_url and source_url != home_url and source_url in sm_result.entries and source_url not in hygiene["redirect"]:
            hygiene["redirect"].append(source_url)
    from datetime import date as _date
    def _day(value):
        try:
            return _date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    hygiene["redirectChains"] = [u for u, pg in crawled_pages.items() if len(pg.get("redirect_chain") or []) > 1]
    hygiene["lastmodMismatch"] = []
    for page_url, page in crawled_pages.items():
        entry = sm_result.entries.get(page_url)
        modified = (page.get("extracted") or {}).get("modified_date")
        if entry and entry.lastmod and modified:
            a, b = _day(entry.lastmod), _day(modified)
            if a and b and abs((a - b).days) > 1:
                hygiene["lastmodMismatch"].append(page_url)
    hreflang_targets = {}
    for page_url, page in crawled_pages.items():
        for h in ((page.get("extracted") or {}).get("hreflang") or []):
            target = canonicalize_crawl_url(h["url"]) or h["url"]
            if target != page_url and target in crawled_pages:
                hreflang_targets.setdefault(page_url, set()).add(target)
    hygiene["hreflangNonReciprocal"] = sorted(
        src for src, targets in hreflang_targets.items()
        if any(src not in hreflang_targets.get(t, set()) for t in targets)
    )
    declared_in_robots = {row["url"] for row in sm_result.sitemaps_found if row.get("source") == "robots.txt"}
    hygiene["undeclaredSitemaps"] = [row["url"] for row in sm_result.sitemaps_found if row.get("source") not in ("robots.txt", "sitemapindex") and row["url"] not in declared_in_robots]
    hygiene["declaredInRobots"] = len(declared_in_robots)
    hygiene = {k: (v[:200] if isinstance(v, list) else v) for k, v in hygiene.items()}
    ai_intel["sitemapHygiene"] = hygiene

    note_by_url: dict[str, str] = {}
    section_by_url: dict[str, str] = {}
    used_note_paths: set[str] = set()

    for u in crawled_pages:
        rel_note, sec = url_to_vault_rel_note(u, domain_folder)
        if u == home_url:
            rel_note = f"sites/{domain_folder}/pages/index.md"
            sec = "root"
        if rel_note in used_note_paths:
            suffix = hashlib.sha256(u.encode("utf-8")).hexdigest()[:6]
            rel_note = f"{rel_note[:-3]}-{suffix}.md"
        used_note_paths.add(rel_note)
        note_by_url[u] = rel_note
        section_by_url[u] = sec

    node_id_by_url: dict[str, str] = {}
    for u in crawled_pages:
        if u == home_url:
            node_id_by_url[u] = "page-home"
        else:
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", urlparse(u).path.strip("/")).strip("-").lower()[:48] or "root"
            short_h = hashlib.sha256(u.encode("utf-8")).hexdigest()[:6]
            node_id_by_url[u] = f"page-{slug}-{short_h}"

    internal_pair_meta: dict[tuple[str, str], dict] = {}
    external_domains: dict[str, dict] = {}
    all_external_urls_raw: set[str] = set()

    for src_u, pdata in crawled_pages.items():
        ext = pdata["extracted"]
        if not ext:
            continue

        for lk in ext["internal_links"]:
            raw_dst = lk["url"]
            dst_u = url_aliases.get(raw_dst, raw_dst)
            if dst_u == src_u or dst_u not in crawled_pages:
                continue
            key = (src_u, dst_u)
            entry = internal_pair_meta.setdefault(
                key,
                {"zones": set(), "body_anchors": [], "chrome_anchors": [], "rels": set()},
            )
            entry["zones"].add(lk["zone"])
            target_list = entry["body_anchors"] if lk["zone"] == "body" else entry["chrome_anchors"]
            if lk["anchor"] and lk["anchor"] not in target_list and len(target_list) < 5:
                target_list.append(lk["anchor"])
            for r in lk["rel"]:
                entry["rels"].add(r)

        for elk in ext["external_links"]:
            edom = elk["domain"]
            if not edom:
                continue
            all_external_urls_raw.add(elk["url"])
            d_bucket = external_domains.setdefault(
                edom,
                {"domain": edom, "urls": set(), "occurrences": [], "source_urls": set()},
            )
            d_bucket["urls"].add(elk["url"])
            d_bucket["source_urls"].add(src_u)
            d_bucket["occurrences"].append(
                {
                    "fromUrl": src_u,
                    "targetUrl": elk["url"],
                    "anchor": elk["anchor"],
                    "rel": elk["rel"],
                    "zone": elk["zone"],
                }
            )

    # Corpus-level boilerplate chrome link refinement:
    # Many custom sites build top bars / breadcrumbs / sticky CTAs out of plain <div>s rather than <nav>/<footer>.
    # If >=8 pages were crawled and a destination receives "body" links from >=65% of pages with short nav-like labels,
    # reclassify those repeated boilerplate links (from non-home pages) as "chrome" so the body graph stays surgical.
    total_crawled_ok = sum(1 for p in crawled_pages.values() if p["extracted"] is not None)
    if total_crawled_ok >= 8:
        body_sources_by_dst: dict[str, list[str]] = {}
        for (src_u, dst_u), meta in internal_pair_meta.items():
            if "body" in meta["zones"]:
                body_sources_by_dst.setdefault(dst_u, []).append(src_u)

        threshold = max(6, int(total_crawled_ok * 0.65))
        for dst_u, srcs in body_sources_by_dst.items():
            if len(srcs) < threshold:
                continue
            for src_u in srcs:
                if src_u == home_url:
                    continue
                meta = internal_pair_meta[(src_u, dst_u)]
                b_anchors = meta["body_anchors"]
                # Keep genuine contextual prose links (longer or varied editorial anchor text)
                if b_anchors and all(len(a) <= 26 for a in b_anchors):
                    meta["zones"].discard("body")
                    meta["zones"].add("chrome")
                    for a in b_anchors:
                        if a not in meta["chrome_anchors"]:
                            meta["chrome_anchors"].append(a)
                    meta["body_anchors"] = []

    inlinks_body_count: dict[str, int] = {u: 0 for u in crawled_pages}
    inlinks_total_count: dict[str, int] = {u: 0 for u in crawled_pages}
    outlinks_body_count: dict[str, int] = {u: 0 for u in crawled_pages}
    outlinks_total_count: dict[str, int] = {u: 0 for u in crawled_pages}

    for (src_u, dst_u), meta in internal_pair_meta.items():
        inlinks_total_count[dst_u] = inlinks_total_count.get(dst_u, 0) + 1
        outlinks_total_count[src_u] = outlinks_total_count.get(src_u, 0) + 1
        if "body" in meta["zones"]:
            inlinks_body_count[dst_u] = inlinks_body_count.get(dst_u, 0) + 1
            outlinks_body_count[src_u] = outlinks_body_count.get(src_u, 0) + 1

    adjacency_all: dict[str, list[str]] = {u: [] for u in crawled_pages}
    for (src_u, dst_u) in internal_pair_meta:
        adjacency_all[src_u].append(dst_u)

    click_depth: dict[str, Optional[int]] = {u: None for u in crawled_pages}
    if home_url in crawled_pages:
        click_depth[home_url] = 0
        bfs = deque([home_url])
        while bfs:
            cur = bfs.popleft()
            d_cur = click_depth[cur] or 0
            for nxt in adjacency_all.get(cur, []):
                if click_depth[nxt] is None:
                    click_depth[nxt] = d_cur + 1
                    bfs.append(nxt)

    has_any_sitemap = len(sitemap_urls) > 0

    section_hub_url: dict[str, str] = {}
    for u in crawled_pages:
        if u == home_url:
            continue
        segs = [s for s in (urlparse(u).path or "/").split("/") if s]
        if len(segs) == 1 and not urlparse(u).query:
            section_hub_url[section_by_url[u]] = u

    graph_nodes: list[dict] = []
    graph_edges: list[dict] = []
    captured_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    sorted_ext_domains = sorted(
        external_domains.values(),
        key=lambda d: (-len(d["source_urls"]), -len(d["urls"]), d["domain"]),
    )

    # Store every observed domain and relationship; display filtering belongs to the UI.
    ext_note_by_domain: dict[str, str] = {}
    ext_node_id_by_domain: dict[str, str] = {}

    for idx_ext, ext_info in enumerate(sorted_ext_domains):
        edom = ext_info["domain"]
        safe_edom = sanitize_slug_segment(edom)
        ext_rel_path = f"sites/{domain_folder}/_external/{safe_edom}.md"
        ext_note_by_domain[edom] = ext_rel_path

        ext_lines = [
            "---",
            f"title: {yaml_quote(edom)}",
            'kind: "external-domain"',
            f"domain: {yaml_quote(edom)}",
            f"site: {yaml_quote(clean_domain)}",
            f"linking_pages_count: {len(ext_info['source_urls'])}",
            f"unique_urls_count: {len(ext_info['urls'])}",
            f"captured_at: {yaml_quote(captured_iso)}",
            "tags:",
            "  - web-obs",
            "  - web-obs/external",
            "---",
            "",
            f"# External Domain: {edom}",
            "",
            f"Referenced by **{len(ext_info['source_urls'])}** internal page(s) on `{clean_domain}` across **{len(ext_info['urls'])}** unique outbound URL(s).",
            "",
            "## Outbound Links from Site",
            "",
            "| Source Page | Anchor Text | Target URL | Zone | Rel |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for occ in ext_info["occurrences"]:
            src_note = note_by_url.get(occ["fromUrl"], "")
            src_link = f"[[{src_note[:-3]}]]" if src_note.endswith(".md") else occ["fromUrl"]
            anc = (occ["anchor"] or "(no text)").replace("|", "-").replace("\n", " ")
            rel_str = ", ".join(occ["rel"]) if occ["rel"] else "dofollow"
            ext_lines.append(
                f"| {src_link} | {anc} | {occ['targetUrl']} | {occ['zone']} | `{rel_str}` |"
            )

        with open(os.path.join(vault_dir, ext_rel_path), "w", encoding="utf-8") as f:
            f.write("\n".join(ext_lines) + "\n")

        ext_id = f"ext-{re.sub(r'[^a-z0-9]+', '-', edom)}-{hashlib.sha256(edom.encode()).hexdigest()[:5]}"
        ext_node_id_by_domain[edom] = ext_id

        sec_counts: dict[str, int] = {}
        for su in ext_info["source_urls"]:
            s_name = section_by_url.get(su, "root")
            sec_counts[s_name] = sec_counts.get(s_name, 0) + 1
        dominant_sec = max(sec_counts.items(), key=lambda kv: kv[1])[0] if sec_counts else "root"
        nofollow_cnt = sum(1 for occ in ext_info["occurrences"] if "nofollow" in occ["rel"])

        graph_nodes.append(
            {
                "id": ext_id,
                "kind": "external-domain",
                "health": "external",
                "flags": [],
                "linkFormMismatches": [],
                "title": edom,
                "url": f"https://{edom}",
                "path": edom,
                "section": dominant_sec,
                "obsidianPath": ext_rel_path,
                "statusCode": 0,
                "responseTimeMs": 0,
                "htmlBytes": 0,
                "inSitemap": False,
                "urlDepth": 0,
                "clickDepth": None,
                "wordCount": 0,
                "readingTimeMin": 0,
                "metaDescription": f"{len(ext_info['urls'])} outbound URL(s) referenced from {len(ext_info['source_urls'])} page(s).",
                "canonical": "",
                "metaRobots": "",
                "lang": "",
                "author": "",
                "publishedDate": "",
                "modifiedDate": "",
                "h1": [],
                "h2Count": 0,
                "schemaTypes": [],
                "imagesCount": 0,
                "localImagesCount": 0,
                "imagesMissingAlt": 0,
                "tablesCount": 0,
                "codeBlocksCount": 0,
                "formsCount": 0,
                "videosCount": 0,
                "seoIssues": [],
                "inlinksBody": len(ext_info["source_urls"]),
                "inlinksTotal": len(ext_info["occurrences"]),
                "outlinksBody": 0,
                "outlinksTotal": 0,
                "externalDomainsOut": 0,
                "externalUrlsSample": sorted(ext_info["urls"])[:12],
                "nofollowCount": nofollow_cnt,
                "renderUsed": False,
            }
        )

    authority_scores = compute_internal_pagerank(list(crawled_pages), internal_pair_meta, home_url)

    # Write internal page notes & build page graph nodes
    deferred_notes: list[tuple[str, str, list[str], list[str]]] = []
    for u, pdata in crawled_pages.items():
        nid = node_id_by_url[u]
        rel_note = note_by_url[u]
        sec = section_by_url[u]
        ext = pdata["extracted"]
        status = pdata["status_code"]
        resp_ms = pdata.get("response_time_ms", 0)
        ttfb_ms = pdata.get("ttfb_ms", 0)
        fetch_ms = pdata.get("fetch_duration_ms", 0)
        redirect_hops = pdata.get("redirect_hops", 0)
        html_bytes = pdata.get("html_bytes", 0)
        in_sm = bool(pdata["in_sitemap"])
        c_depth = click_depth.get(u)
        segs = [s for s in (urlparse(u).path or "/").split("/") if s]
        u_depth = 0 if u == home_url else len(segs)

        is_section_hub = (
            u != home_url
            and (section_hub_url.get(sec) == u or (u_depth == 1 and inlinks_total_count.get(u, 0) >= 2))
        )

        if status in (404, 410):
            health = "broken"
            kind = "page"
        elif status >= 400 or status == 0 or pdata["error"]:
            health = "unavailable"
            kind = "page"
        elif pdata["redirect_chain"] and u != home_url:
            health = "redirect"
            kind = "page"
        elif u == home_url:
            health = "home"
            kind = "home"
        elif c_depth is None or inlinks_total_count.get(u, 0) == 0:
            health = "orphan"
            kind = "hub" if is_section_hub else "page"
        elif has_any_sitemap and not in_sm and "noindex" not in ((ext or {}).get("meta_robots") or "").lower():
            health = "unlisted"
            kind = "hub" if is_section_hub else "page"
        elif is_section_hub:
            health = "hub"
            kind = "hub"
        else:
            health = "healthy"
            kind = "page"

        title = (ext["title"] if ext else None) or urlparse(u).path or u
        meta_desc = ext["meta_description"] if ext else ""
        canonical = ext["canonical"] if ext else ""
        meta_robots = ext["meta_robots"] if ext else ""
        lang = ext.get("lang", "") if ext else ""
        author = ext.get("author", "") if ext else ""
        pub_date = ext.get("published_date", "") if ext else ""
        mod_date = ext.get("modified_date", "") if ext else ""
        h1_list = ext["h1"] if ext else []
        h2_list = ext["h2"] if ext else []
        schema_types = ext["schema_types"] if ext else []
        word_count = ext["word_count"] if ext else 0
        reading_min = ext.get("reading_time_min", 0) if ext else 0
        content_hash = ext.get("content_hash", "") if ext else ""
        images_count = len(ext["images"]) + len(ext.get("inline_svgs") or []) if ext else 0
        images_missing_alt = ext.get("images_missing_alt", 0) if ext else 0
        images_empty_alt = ext.get("images_empty_alt", 0) if ext else 0
        template_heading_skips = ext.get("template_heading_skips", 0) if ext else 0
        tables_count = ext.get("tables_count", 0) if ext else 0
        code_blocks_count = ext.get("code_blocks_count", 0) if ext else 0
        forms_count = len(ext.get("forms") or []) if ext else 0
        videos_list = ext.get("videos") or [] if ext else []
        downloads_list = ext.get("downloads") or [] if ext else []
        page_resources = [r for r in resources if any(ref['pageUrl'] == u for ref in r['references'])]
        page_issues = list(ext.get("seo_issues") or []) if ext else []
        if pdata.get("render_used"):
            # The browser proxy drops Content-Encoding, so compression is unknown for rendered pages.
            page_issues = [i for i in page_issues if i != "no-compression"]
        if health in ("broken", "unavailable"):
            page_issues.append("page-" + health)
        # Independent flags: a page can be a redirect and also missing from the sitemap, so the
        # single health value (kept for colours and the map) never decides these counts.
        fetched_ok = health not in ("broken", "unavailable")
        noindex_page = "noindex" in ((ext or {}).get("meta_robots") or "").lower()
        page_flags: list[str] = []
        if pdata["redirect_chain"] and u != home_url:
            page_flags.append("redirect")
        if fetched_ok and u != home_url and (c_depth is None or inlinks_total_count.get(u, 0) == 0):
            page_flags.append("orphan")
        if fetched_ok and u != home_url and has_any_sitemap and not in_sm and not noindex_page:
            page_flags.append("unlisted")
        if noindex_page:
            page_flags.append("noindex")
        if "orphan" in page_flags:
            page_issues.append("orphan-page")
        if "unlisted" in page_flags:
            page_issues.append("unlisted-in-sitemap")
        if pdata["redirect_chain"]:
            page_issues.append("redirected-source-url")
        form_mismatches = link_form_mismatches.get(u) or {}
        if form_mismatches:
            page_issues.append(f"internal-link-form-mismatch ({len(form_mismatches)})")
        local_imgs = pdata["local_images"]

        page_ext_domains: dict[str, list[dict]] = {}
        if ext:
            for elk in ext["external_links"]:
                page_ext_domains.setdefault(elk["domain"], []).append(elk)

        tag_health = f"web-obs/{'page' if health == 'healthy' else health}"
        frontmatter_lines = [
            "---",
            f"title: {yaml_quote(title)}",
            f"url: {yaml_quote(u)}",
            f"site: {yaml_quote(clean_domain)}",
            f"brand: {yaml_quote(brand_name)}",
            f"section: {yaml_quote(sec)}",
            f"kind: {yaml_quote(kind)}",
            f"path: {yaml_quote(urlparse(u).path or chr(47))}",
            f"authority_score: {authority_scores.get(u, 0)}",
            f"seo_issues_count: {len(page_issues)}",
            f"cover: {yaml_quote(chr(91) + chr(91) + local_imgs[0] + chr(93) + chr(93) if local_imgs else chr(32))}",
            f"health: {yaml_quote(health)}",
            f"status_code: {status}",
            f"response_time_ms: {resp_ms}",
            f"ttfb_ms: {ttfb_ms}",
            f"redirect_hops: {redirect_hops}",
            f"html_kb: {round(html_bytes / 1024, 1)}",
            f"in_sitemap: {'true' if in_sm else 'false'}",
            f"url_depth: {u_depth}",
            f"click_depth: {c_depth if c_depth is not None else 'null'}",
            f"word_count: {word_count}",
            f"reading_time_min: {reading_min}",
            f"lang: {yaml_quote(lang)}",
            f"author: {yaml_quote(author)}",
            f"published_date: {yaml_quote(pub_date)}",
            f"modified_date: {yaml_quote(mod_date)}",
            f"meta_description: {yaml_quote(meta_desc)}",
            f"canonical: {yaml_quote(canonical)}",
            f"meta_robots: {yaml_quote(meta_robots)}",
            f"h1: {yaml_quote(h1_list[0] if h1_list else '')}",
            f"images_count: {images_count}",
            f"local_images_count: {len(local_imgs)}",
            f"images_missing_alt: {images_missing_alt}",
            f"tables_count: {tables_count}",
            f"code_blocks_count: {code_blocks_count}",
            f"forms_count: {forms_count}",
            f"videos_count: {len(videos_list)}",
            f"inlinks_body: {inlinks_body_count.get(u, 0)}",
            f"inlinks_total: {inlinks_total_count.get(u, 0)}",
            f"outlinks_body: {outlinks_body_count.get(u, 0)}",
            f"outlinks_total: {outlinks_total_count.get(u, 0)}",
            f"external_domains_count: {len(page_ext_domains)}",
            f"content_hash: {yaml_quote(content_hash)}",
            f"captured_at: {yaml_quote(captured_iso)}",
            "tags:",
            "  - web-obs",
            f"  - {tag_health}",
        ]
        if schema_types:
            frontmatter_lines.append("schema_types:")
            for st in schema_types[:12]:
                frontmatter_lines.append(f"  - {yaml_quote(st)}")
        if page_issues:
            frontmatter_lines.append("seo_issues:")
            for iss in page_issues[:40]:
                frontmatter_lines.append(f"  - {yaml_quote(iss)}")
        frontmatter_lines.append("---")

        md_body = ""
        if ext and ext["markdown"]:
            md_body = rewrite_markdown_for_obsidian(
                ext["markdown"],
                u,
                note_by_url,
                url_aliases,
                image_file_by_url,
                domain_folder,
            )

        note_sections: list[str] = ["\n".join(frontmatter_lines), ""]
        if local_imgs:
            note_sections.append(f"![[{local_imgs[0]}|Cover]]")
            note_sections.append("")

        note_sections.append(f"# {title}")
        note_sections.append("")
        if meta_desc:
            note_sections.append(f"> {meta_desc}")
            note_sections.append("")

        hops = pdata["redirect_chain"] or []
        reached_via = ", ".join(f"{hop.get('status_code')} from {hop.get('url')}" for hop in hops[:3]) if hops else ""
        health_word = {"healthy": "Healthy", "hub": "Section hub", "home": "Home", "orphan": "Orphan (no internal links in)",
                       "unlisted": "Not in the sitemap", "redirect": "Redirects", "broken": "Broken", "unavailable": "Unavailable"}.get(health, health)
        note_sections.extend(property_table([
            ("URL", f"[{_md_label(urlparse(u).path or '/', 80)}]({u})"),
            ("Status", f"{status} · {resp_ms} ms" if status else "No response"),
            ("Reached via redirect", reached_via),
            ("Health", health_word),
            ("Click depth", str(c_depth) if c_depth is not None else "Not linked from home"),
            ("In sitemap", "Yes" if in_sm else "No"),
            ("Words", f"{word_count:,} (about {reading_min} min read)"),
        ]))
        note_sections.append("")

        if pdata["error"]:
            note_sections.append(f"> [!WARNING] Crawl Error\n> {pdata['error']}")
            note_sections.append("")

        regions = (ext or {}).get("site_regions") or []
        if md_body or regions:
            note_sections.append("## Page Content")
            note_sections.append("")
            for region in (r for r in regions if r.get("position") == "before"):
                callout = region_callout(region)
                if callout:
                    note_sections.extend(callout + [""])
            if md_body:
                note_sections.append(md_body)
                note_sections.append("")
            for region in (r for r in regions if r.get("position") != "before"):
                callout = region_callout(region)
                if callout:
                    note_sections.extend(callout + [""])

        if videos_list:
            note_sections.append("## Embedded & Linked Videos")
            note_sections.append("")
            for v_u in videos_list:
                note_sections.append(f"- {v_u}")
            note_sections.append("")

        if downloads_list:
            note_sections.append("## Downloadable Files")
            note_sections.append("")
            for dl in downloads_list:
                note_sections.append(f"- [{dl['label']}]({dl['url']})")
            note_sections.append("")

        if page_resources:
            note_sections.extend(media_section(page_resources, u))

        body_targets: list[tuple[str, list[str]]] = []
        chrome_targets: list[tuple[str, list[str]]] = []
        for (src_u, dst_u), meta in internal_pair_meta.items():
            if src_u != u:
                continue
            if "body" in meta["zones"]:
                body_targets.append((dst_u, meta["body_anchors"]))
            else:
                chrome_targets.append((dst_u, meta["chrome_anchors"]))

        if body_targets:
            note_sections.append("## Contextual Internal Links")
            note_sections.append("")
            for dst_u, anchors in body_targets:
                dst_note = note_by_url[dst_u][:-3]
                anc_txt = f" ({', '.join(anchors[:2])})" if anchors else ""
                note_sections.append(f"- [[{dst_note}]]{anc_txt}")
            note_sections.append("")

        if page_ext_domains:
            note_sections.append("## Outgoing External Links")
            note_sections.append("")
            for edom, elist in sorted(page_ext_domains.items()):
                hub = f"[[{ext_note_by_domain[edom][:-3]}|{edom}]]" if edom in ext_note_by_domain else edom
                links: dict[str, str] = {}
                for item in elist:
                    links.setdefault(item["url"], item.get("anchor") or "")
                if len(links) == 1:
                    link_url, anchor = next(iter(links.items()))
                    note_sections.append(f"- [{_md_label(anchor) or _md_label(urlparse(link_url).path or link_url, 70)}]({link_url}) · {hub}")
                    continue
                note_sections.append(f"- {hub}")
                for link_url, anchor in sorted(links.items())[:12]:
                    note_sections.append(f"  - [{_md_label(anchor) or _md_label(urlparse(link_url).path or link_url, 70)}]({link_url})")
                if len(links) > 12:
                    note_sections.append(f"  - and {len(links) - 12} more")
            note_sections.append("")

        if chrome_targets:
            note_sections.append("## Navigation & Footer Links (Site Chrome)")
            note_sections.append("")
            chrome_urls = {dst_u: anchors for dst_u, anchors in chrome_targets}
            def _key(link_url):
                norm = canonicalize_crawl_url(link_url) or link_url
                return url_aliases.get(norm, norm)
            groups = [("Header", (ext or {}).get("header_nav") or []), ("Footer", (ext or {}).get("footer_links") or [])]
            placed: set[str] = set()
            for group_title, group_links in groups:
                rows = []
                for link in group_links:
                    key = _key(link.get("url") or "")
                    if key in chrome_urls and key not in placed:
                        placed.add(key)
                        rows.append((key, link.get("label") or ""))
                if rows:
                    note_sections.append(f"**{group_title}**")
                    note_sections.extend(f"- [{_md_label(label) or _md_label((crawled_pages[key].get('extracted') or {}).get('title') or key)}]({key})" for key, label in rows[:25])
                    note_sections.append("")
            other = [(dst_u, anchors) for dst_u, anchors in chrome_targets if dst_u not in placed]
            if other:
                note_sections.append("**Other site navigation**" if placed else "**Site navigation**")
                for dst_u, anchors in other[:25]:
                    label = anchors[0] if anchors else (crawled_pages[dst_u].get("extracted") or {}).get("title") or dst_u
                    note_sections.append(f"- [{_md_label(label)}]({dst_u})")
                note_sections.append("")

        # Notes are written after the site audit so each one can carry its own findings.
        deferred_notes.append((u, os.path.join(vault_dir, rel_note), frontmatter_lines, note_sections[1:]))

        path_display = urlparse(u).path or "/"
        if urlparse(u).query:
            path_display = f"{path_display}?{urlparse(u).query}"

        graph_nodes.append(
            {
                "id": nid,
                "kind": kind,
                "health": health,
                "flags": page_flags,
                "linkFormMismatches": [{"linked": linked, "published": published} for linked, published in sorted(form_mismatches.items())[:10]],
                "title": title,
                "url": u,
                "path": path_display,
                "section": sec,
                "obsidianPath": rel_note,
                "statusCode": status,
                "fetchStatus": "unavailable" if pdata["error"] else "complete",
                "error": pdata["error"],
                "errorKind": pdata.get("error_kind"),
                "resourceIds": [r['id'] for r in page_resources],
                "audioCount": sum(r['type'] == 'audio' for r in page_resources),
                "transcriptsCount": sum(r['type'] == 'transcript' for r in page_resources),
                "authorityScore": authority_scores.get(u, 0),
                "contentHash": content_hash,
                "rawPath": next((r.get("rawPath") for r in fetch_rows if r["url"] == u), None),
                "responseTimeMs": resp_ms,
                "ttfbMs": ttfb_ms,
                "fetchDurationMs": fetch_ms,
                "redirectHops": redirect_hops,
                "htmlBytes": html_bytes,
                "inSitemap": in_sm,
                "urlDepth": u_depth,
                "clickDepth": c_depth,
                "wordCount": word_count,
                "readingTimeMin": reading_min,
                "metaDescription": meta_desc,
                "canonical": canonical,
                "metaRobots": meta_robots,
                "lang": lang,
                "author": author,
                "publishedDate": pub_date,
                "modifiedDate": mod_date,
                "h1": h1_list[:4],
                "h2Count": len(h2_list),
                "schemaTypes": schema_types[:10],
                "imagesCount": images_count,
                "localImagesCount": len(local_imgs),
                "imagesMissingAlt": images_missing_alt,
                "imagesEmptyAlt": images_empty_alt,
                "templateHeadingSkips": template_heading_skips,
                "tablesCount": tables_count,
                "codeBlocksCount": code_blocks_count,
                "formsCount": forms_count,
                "videosCount": len(videos_list),
                "seoIssues": page_issues[:40],
                "pageChecks": (ext or {}).get("page_checks"),
                "simhash": (ext or {}).get("simhash", ""),
                "keywords": {k: v[:5] for k, v in ((ext or {}).get("keywords") or {}).items() if isinstance(v, list)},
                "coverAsset": local_imgs[0] if local_imgs else None,
                "inlinksBody": inlinks_body_count.get(u, 0),
                "inlinksTotal": inlinks_total_count.get(u, 0),
                "outlinksBody": outlinks_body_count.get(u, 0),
                "outlinksTotal": outlinks_total_count.get(u, 0),
                "externalDomainsOut": len(page_ext_domains),
                "redirectChain": pdata["redirect_chain"],
                "renderUsed": bool(pdata["render_used"]),
            }
        )

    edge_counter = 0
    existing_body_pairs: set[tuple[str, str]] = set()

    for (src_u, dst_u), meta in internal_pair_meta.items():
        src_id = node_id_by_url[src_u]
        dst_id = node_id_by_url[dst_u]
        edge_counter += 1
        is_body = "body" in meta["zones"]
        if is_body:
            existing_body_pairs.add((src_id, dst_id))
        anchors = meta["body_anchors"] if is_body else meta["chrome_anchors"]
        graph_edges.append(
            {
                "id": f"e-int-{edge_counter}",
                "source": src_id,
                "target": dst_id,
                "kind": "internal-body" if is_body else "internal-chrome",
                "anchor": anchors[0] if anchors else "",
                "rel": sorted(meta["rels"]),
            }
        )

    home_id = node_id_by_url.get(home_url)
    for u in crawled_pages:
        if u == home_url:
            continue
        nid = node_id_by_url[u]
        sec = section_by_url[u]
        hub_u = section_hub_url.get(sec)
        parent_id = None
        if hub_u and hub_u != u:
            parent_id = node_id_by_url.get(hub_u)
        elif home_id:
            parent_id = home_id
        if parent_id and (parent_id, nid) not in existing_body_pairs:
            if click_depth.get(u) is None:
                continue
            edge_counter += 1
            graph_edges.append(
                {
                    "id": f"e-hier-{edge_counter}",
                    "source": parent_id,
                    "target": nid,
                    "kind": "sitemap-hierarchy",
                    "anchor": f"/{sec}" if sec != "root" else clean_domain,
                    "rel": [],
                }
            )

    for edom, ext_id in ext_node_id_by_domain.items():
        ext_info = external_domains[edom]
        by_src: dict[str, list[dict]] = {}
        for occ in ext_info["occurrences"]:
            by_src.setdefault(occ["fromUrl"], []).append(occ)
        for src_u, occs in by_src.items():
            if src_u not in node_id_by_url:
                continue
            edge_counter += 1
            has_body = any(o["zone"] == "body" for o in occs)
            rels = sorted({r for o in occs for r in o["rel"]})
            graph_edges.append(
                {
                    "id": f"e-ext-{edge_counter}",
                    "source": node_id_by_url[src_u],
                    "target": ext_id,
                    "kind": "external",
                    "zone": "body" if has_body else "chrome",
                    "anchor": occs[0]["anchor"] if occs else edom,
                    "targetUrl": occs[0]["targetUrl"] if occs else f"https://{edom}",
                    "count": len(occs),
                    "rel": rels,
                }
            )

    section_counts: dict[str, int] = {}
    for n in graph_nodes:
        if n["kind"] == "external-domain":
            continue
        section_counts[n["section"]] = section_counts.get(n["section"], 0) + 1

    sections_summary = [
        {"id": sec_id, "label": clean_domain if sec_id == "root" else f"/{sec_id}", "pageCount": cnt}
        for sec_id, cnt in sorted(section_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    internal_only = [n for n in graph_nodes if n["kind"] != "external-domain"]
    orphans = [n for n in internal_only if "orphan" in n["flags"]]
    unlisted = [n for n in internal_only if "unlisted" in n["flags"]]
    broken = [n for n in internal_only if n["health"] in ("broken", "redirect")]

    # Aggregate contacts, clean social profiles, videos, forms, downloads, RSS, hreflang
    all_emails: set[str] = set()
    all_phones: set[str] = set()
    clean_socials: set[str] = set()
    all_videos: set[str] = set()
    all_downloads: dict[str, str] = {}
    all_rss_feeds: set[str] = set()
    all_languages: set[str] = set()
    total_forms = 0
    root_schemas: list[dict] = []

    for u, pdata in crawled_pages.items():
        ext = pdata.get("extracted")
        if not ext:
            continue
        for em in ext.get("emails", []):
            all_emails.add(em)
        for ph in ext.get("phones", []):
            all_phones.add(ph)
        if ext.get("lang"):
            all_languages.add(ext["lang"])
        for rf in ext.get("rss_feeds", []):
            all_rss_feeds.add(rf)
        for vid_u in ext.get("videos", []):
            all_videos.add(vid_u)
        for dl in ext.get("downloads", []):
            all_downloads[dl["url"]] = dl["label"]
        total_forms += len(ext.get("forms") or [])

        if u == home_url:
            root_schemas = ext.get("schema_blocks", [])[:12]
            for blk in root_schemas:
                same_as = blk.get("sameAs")
                if isinstance(same_as, list):
                    for s_url in same_as:
                        if isinstance(s_url, str) and s_url.startswith("http"):
                            prof = is_clean_social_profile_url(s_url) or s_url
                            clean_socials.add(prof)
                elif isinstance(same_as, str) and same_as.startswith("http"):
                    prof = is_clean_social_profile_url(same_as) or same_as
                    clean_socials.add(prof)

        for elk in ext.get("external_links", []):
            prof = is_clean_social_profile_url(elk["url"])
            if prof:
                clean_socials.add(prof)

    funnel_platforms = detect_funnel_platforms(sorted(all_external_urls_raw))
    resp_times = [n["responseTimeMs"] for n in internal_only if n.get("responseTimeMs", 0) > 0]
    avg_ttfb_ms = int(round(sum(resp_times) / len(resp_times))) if resp_times else 0
    sorted_times = sorted(resp_times)
    median_response_ms = int(round(sorted_times[len(sorted_times) // 2])) if sorted_times else 0
    fetch_times = [n["fetchDurationMs"] for n in internal_only if n.get("fetchDurationMs", 0) > 0]
    avg_fetch_ms = int(round(sum(fetch_times) / len(fetch_times))) if fetch_times else 0
    pages_with_seo_issues = sum(1 for n in internal_only if n.get("seoIssues"))
    all_schema_types = sorted({st for n in internal_only for st in n.get("schemaTypes", []) if st})

    from site_intel import summarize_link_results
    link_health = summarize_link_results(collected["link_results"], 1000 if check_external else 0, 30)
    link_health["scope"] = "External destinations and observed media/resources"
    with open(os.path.join(site_root, "_resources.json"), "w", encoding="utf-8") as f:
        json.dump({"resources": resources, "metrics": collected["metrics"]}, f, indent=2, ensure_ascii=False)
    resource_lines = ["# Media and Resource Inventory", "", "Resources are associated with their source pages and kept outside the HTML page graph.", "Large audio and video files are referenced without downloading their bodies.", "", "| Type | URL | Check | Saved file | Source pages |", "| :--- | :--- | :--- | :--- | :--- |"]
    for resource in resources:
        values = [resource['type'], resource['url'], resource['checkStatus'], resource.get('localPath') or 'Reference only', ', '.join(sorted({r['pageUrl'] for r in resource['references']}))]
        resource_lines.append('| ' + ' | '.join(str(v).replace('|', '\\|').replace('\n', ' ') for v in values) + ' |')
    with open(os.path.join(site_root, "_resources.md"), "w", encoding="utf-8") as f:
        f.write('\n'.join(resource_lines) + '\n')
    with open(os.path.join(site_root, "_link-health.json"), "w", encoding="utf-8") as f:
        json.dump(link_health, f, indent=2, ensure_ascii=False)
    link_lines = ["# Direct link and resource checks", "", f"Observed targets: {link_health['totalCount']}. Attempted: {link_health['checkedCount']}. Unchecked: {link_health['uncheckedCount']}.", "", "A request attempt does not establish that a target is healthy. 403/429 and transport failures remain unknown.", "", "| URL | Result | HTTP | Reason |", "| :--- | :--- | :--- | :--- |"]
    for row in link_health["results"]:
        values = [row.get("url", ""), row.get("status", "unknown"), str(row.get("statusCode") or "No data"), row.get("reason", "")]
        link_lines.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    with open(os.path.join(site_root, "_link-health.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(link_lines) + "\n")
    home_record = next((p for p in page_records if p["url"] == home_url), {})
    home_raw = source_artifacts.get(home_record.get("url"), {}).get("rawPath")
    home_html = ""
    if home_raw:
        with open(os.path.join(site_root, home_raw), encoding="utf-8", errors="strict") as home_source:
            home_html = home_source.read()
    brand_kit = extract_observed_brand_kit(home_html, home_url, (home_ext or {}).get("schema_blocks"), downloader, domain_folder, allow_url=allow_resource, source_artifacts=source_artifacts, site_root=site_root)
    write_fetch_log(site_root, clean_domain, origin, captured_iso, fetch_rows)
    previous_site_root = os.path.join(previous_vault_dir, "sites", domain_folder) if previous_vault_dir else None
    drift = compute_and_write_site_drift(site_root, clean_domain, captured_iso, previous_manifest, internal_only, sorted(external_domains), new_edges=graph_edges, capture_status=capture_status,
        previous_site_root=previous_site_root, home_url=home_url,
        security_headers_present=stack_intel["securityHeaders"]["present"] if home_headers else None)
    site_intel_bundle = {
        "brandName": brand_name,
        "languages": sorted(all_languages),
        "rssFeeds": sorted(all_rss_feeds)[:10],
        "avgResponseTimeMs": avg_ttfb_ms,
        "totalAssetsMb": round((downloader.total_bytes / (1024 * 1024)), 2) if downloader else 0.0,
        "contacts": {
            "emails": sorted(all_emails),
            "phones": sorted(all_phones),
            "socialProfiles": sorted(clean_socials)[:25],
        },
        "techStack": stack_intel,
        "aiReadiness": ai_intel,
        "funnel": {
            "formsCount": total_forms,
            "videosCount": len(all_videos),
            "downloadsCount": len(all_downloads),
            "platforms": funnel_platforms,
        },
    }

    # Site audit, browser sample and transport checks
    emit_event("phase", phase="compile", message="Auditing duplicates, link graph, schema, certificate and a browser sample...")
    extracted_by_url = {u: p["extracted"] for u, p in crawled_pages.items() if p.get("extracted")}
    try:
        audit = build_site_audit(nodes=internal_only, extracted_by_url=extracted_by_url, internal_pair_meta=internal_pair_meta,
            redirects=fetch_redirects, home_url=home_url, origin=origin, brand=brand_name, resources=resources,
            sitemaps_found=sm_result.sitemaps_found, sitemap_urls=list(sitemap_urls), robots_text=sm_result.robots_text,
            captured_iso=captured_iso, brand_kit=brand_kit)
    except Exception as exc:  # An unusual page must never cost the member the whole capture.
        capture_warnings.append(f"The site audit could not finish ({type(exc).__name__}: {exc}). Page notes and the map were still saved.")
        capture_status = "partial"
        audit = build_site_audit(nodes=[], extracted_by_url={}, internal_pair_meta={}, redirects={}, home_url=home_url, origin=origin,
            brand=brand_name, resources=[], sitemaps_found=[], sitemap_urls=[], robots_text="", captured_iso=captured_iso)
        audit["error"] = f"{type(exc).__name__}: {exc}"
    from url_safety import capture_out_of_time, capture_time_left, within_capture_deadline

    def out_of_time(what: str, need_sec: float) -> bool:
        """A phase with too little time left is skipped and said so, rather than run into a timeout."""
        if capture_out_of_time(need_sec):
            capture_warnings.append(f"The capture deadline was reached before {what}.")
            return True
        return False

    browser_result = {"state": "skipped", "detail": "Browser audit turned off for this capture.", "pages": [], "findings": []}
    if browser_audit and out_of_time("the browser sample", 15):
        browser_result = {"state": "skipped", "detail": "The capture deadline was reached before the browser sample.", "pages": [], "findings": []}
    elif browser_audit:
        from browser_audit import run_browser_audit
        ranked = sorted((n for n in internal_only if n["statusCode"] == 200 and n["health"] in ("home", "hub", "healthy", "unlisted")),
                        key=lambda n: (n["url"] != home_url, -(n.get("authorityScore") or 0), n["url"]))
        sample_urls = [n["url"] for n in ranked[:5]]
        raw_html_by_url = {}
        for record in page_records:
            if record["url"] in sample_urls and record.get("rawKind") == "http-response-decoded" and not crawled_pages[record["url"]].get("render_used"):
                source = record.get("textPath") or record.get("rawPath")
                if source:
                    with open(os.path.join(site_root, source), "rb") as raw_file:
                        raw_html_by_url[record["url"]] = raw_file.read().decode("utf-8", errors="replace")
        browser_result = run_browser_audit(sample_urls, site_root=site_root, domain_folder=domain_folder,
            allow_url=allow_page, allow_resource_url=allow_resource, raw_html_by_url=raw_html_by_url, render_mode=render_mode,
            time_budget_sec=within_capture_deadline(90))
    snapshot_result = {"state": "skipped", "detail": "Page snapshots are turned off for this capture.", "pages": {}, "limit": 0}
    if snapshot_limit > 0 and out_of_time("the page snapshots", 15):
        snapshot_result = {"state": "skipped", "detail": "The capture deadline was reached before the page snapshots.", "pages": {}, "limit": snapshot_limit}
    elif snapshot_limit > 0:
        from page_snapshots import run_page_snapshots
        emit_event("phase", phase="snapshots", message="Saving full-page snapshots...")
        snapshot_order = [n["url"] for n in sorted((n for n in internal_only if n["statusCode"] == 200 and n["health"] in ("home", "hub", "healthy", "unlisted", "orphan")),
                          key=lambda n: (n["url"] != home_url, -(n.get("authorityScore") or 0), n["url"]))]
        snapshot_result = run_page_snapshots(snapshot_order, site_root=site_root, limit=snapshot_limit, save_html=snapshot_html,
            allow_url=allow_page, allow_resource_url=allow_resource, render_mode=render_mode,
            time_budget_sec=within_capture_deadline(max(60, min(900, 15 * snapshot_limit))))  # about 15 s for a load plus a 24,000 px scroll
        nodes_by_snapshot_url = {n["url"]: n for n in internal_only}
        for snap_url, snap in (snapshot_result.get("pages") or {}).items():
            if snap.get("screenshot") and snap_url in nodes_by_snapshot_url:
                nodes_by_snapshot_url[snap_url]["snapshot"] = {k: snap.get(k) for k in ("screenshot", "html", "heightPx", "truncated", "capPx", "hiddenOverlays")}
    from transport_checks import analyze_header_quality, check_email_dns, check_tls_certificate, set_cookie_values, transport_findings
    if not tls_check:
        tls_result = {"state": "skipped", "detail": "The certificate check is turned off for this capture."}
    elif out_of_time("the certificate check", 2):
        tls_result = {"state": "skipped", "detail": "The capture deadline was reached before the certificate check."}
    else:
        tls_result = check_tls_certificate(origin, timeout=within_capture_deadline(6.0))
    header_quality = analyze_header_quality(home_headers or {}, set_cookie_values(home_headers or {}), https=parsed_origin.scheme == "https")
    host_is_ip = bool(re.fullmatch(r"[0-9.]+|.*:.*", target_host))
    if dns_checks and not host_is_ip and out_of_time("the email DNS checks", 2):
        email_dns = {"state": "skipped", "detail": "The capture deadline was reached before the email DNS checks."}
    elif dns_checks and not host_is_ip:
        email_dns = check_email_dns(clean_domain, budget_sec=capture_time_left())
    else:
        email_dns = {"state": "skipped", "detail": "DNS checks are turned off or the site is addressed by IP."}
    transport = {"tls": tls_result, "headerQuality": header_quality, "emailDns": email_dns}
    alternate = ((ai_intel.get("siteChecks") or {}).get("alternateHost") or {}).get("state")
    t_findings = [f for f in transport_findings(tls_result, header_quality, email_dns, home_url)
                  if not (f["id"] == "tls-alternate-host" and alternate != "unreachable")]
    site_intel_bundle["browserAudit"] = browser_result
    site_intel_bundle["snapshots"] = {k: v for k, v in snapshot_result.items() if k != "pages"}
    site_intel_bundle["transport"] = transport
    site_intel_bundle["pageCheckFeatures"] = page_checks.optional_feature_states()
    audit["findings"] = (page_findings(internal_only) + audit["findings"] + list(browser_result.get("findings") or [])
                         + t_findings
                         + security_txt_findings(ai_intel, origin, datetime.now(timezone.utc).date()) + drift_findings(drift))
    findings_by_url: dict[str, list] = {}
    for finding in audit["findings"]:
        if finding["id"].startswith("seo:"):
            continue
        for target in finding["targets"]:
            for key in {target.get("url"), target.get("sourceUrl")}:
                if key in note_by_url:
                    findings_by_url.setdefault(key, []).append((finding, target))
    browser_by_url = {p["url"]: p for p in browser_result.get("pages") or []}
    node_by_url = {n["url"]: n for n in internal_only}
    opportunities_by_source = {}
    for row in audit["linkOpportunities"]:
        opportunities_by_source[row["sourceUrl"]] = opportunities_by_source.get(row["sourceUrl"], 0) + 1
    duplicate_urls = {u for key in ("titles", "descriptions") for g in audit["duplicates"][key] for u in g["urls"]}
    duplicate_urls |= {u for key in ("exactContent", "nearContent") for g in audit["duplicates"][key] for u in g["urls"]}
    for u, note_path, frontmatter, body in deferred_notes:
        node = node_by_url[u]
        checks = node.get("pageChecks") or {}
        extra = [f"findings_count: {len(node.get('seoIssues') or []) + len(findings_by_url.get(u, []))}",
                 f"text_ratio: {round((checks.get('textRatio') or 0) * 100, 1)}",
                 f"readability: {((checks.get('readability') or {}).get('fleschReadingEase')) if checks.get('readability') else 'null'}",
                 f"dom_nodes: {(checks.get('dom') or {}).get('nodes', 0)}",
                 f"duplicate: {'true' if u in duplicate_urls else 'false'}",
                 f"link_opportunities: {opportunities_by_source.get(u, 0)}"]
        fm = frontmatter[:-1] + extra + [frontmatter[-1]]
        audit_lines = page_audit_section(u, node, findings_by_url, checks or None, browser_by_url.get(u), domain_folder)
        snap = node.get("snapshot") or {}
        if snap.get("screenshot"):
            callout = [f"> [!example]- Page snapshot", f"> ![[sites/{domain_folder}/{snap['screenshot']}|Full-page snapshot]]"]
            note_bits = ["rendered once at 1280 px wide"]
            if snap.get("truncated"):
                note_bits.append(f"cut at {snap.get('capPx') or 12000:,} px of {snap.get('heightPx'):,}")
            if snap.get("hiddenOverlays"):
                note_bits.append("pinned banners such as cookie notices hidden")
            if snap.get("html"):
                note_bits.append(f"[[sites/{domain_folder}/{snap['html']}|rendered HTML]]")
            caption = "; ".join(note_bits)
            callout.append(f"> *{caption[:1].upper() + caption[1:]}.*")
            title_at = next((i for i, line in enumerate(body) if line.startswith("# ")), None)
            insert_at = (title_at + 1) if title_at is not None else 0
            body = body[:insert_at] + ["", *callout] + body[insert_at:]
        os.makedirs(os.path.dirname(note_path), exist_ok=True)
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("\n".join(["\n".join(fm), *body, *audit_lines]).rstrip() + "\n")
    write_findings_csv(site_root, audit["findings"])
    ok_page_urls = {u for u, p in crawled_pages.items() if p.get("extracted") and isinstance(p.get("status_code"), int) and 200 <= p["status_code"] < 300}
    checks_ran = {"browserUrls": {p["url"] for p in browser_result.get("pages") or [] if not p.get("error")},
                  "tls": tls_result.get("state") in ("ok", "warn", "fail"),
                  "dns": email_dns.get("state") in ("ok", "warn", "fail"),
                  "headers": bool(home_headers), "robots": bool(sm_result.robots_text)}
    if capture_warnings:
        capture_status = "partial"
    # --no-tasks: no _tasks.md (for a host app that keeps its own task list).
    task_counts = write_tasks(site_root, previous_site_root, audit["findings"], captured_iso,
        set(crawled_pages), capture_status == "complete", note_by_url, ok_urls=ok_page_urls, checks_ran=checks_ran) if tasks else None
    audit["tasks"] = task_counts
    write_audit_report(site_root, domain_folder, clean_domain, captured_iso, audit, note_by_url, transport, browser_result, task_counts)
    audit_summary = {"findings": len(audit["findings"]), "findingItems": sum(f.get("targetCount", len(f["targets"])) for f in audit["findings"]),
                     "linkOpportunities": len(audit["linkOpportunities"]), "linkFixes": len(audit["linkFixes"]),
                     "duplicateGroups": sum(len(audit["duplicates"][k]) for k in ("titles", "descriptions", "exactContent", "nearContent")),
                     "tasks": task_counts}

    manifest = {
        "schemaVersion": "1.3.0",
        "audit": audit,
        "issueCatalog": catalog_for_manifest(),
        "resources": resources,
        "pipelineMetrics": collected["metrics"],
        "captureProvenance": provenance,
        "reclassifiedPagePaths": [n["obsidianPath"].removeprefix(f"sites/{domain_folder}/") for n in (previous_manifest or {}).get("nodes", []) if n.get("url") in {r['url'] for r in resources} and n.get("kind") != 'external-domain'],
        "captureStatus": capture_status,
        "captureWarnings": capture_warnings,
        "captureFindings": capture_findings[:200],
        "siteId": domain_folder,
        "domain": clean_domain,
        "brandName": brand_name,
        "origin": origin,
        "capturedAt": captured_iso,
        "elapsedSec": round(time.time() - started_at, 2),
        "stats": {
            "pagesCrawled": len(internal_only),
            "sitemapsFound": len(sm_result.sitemaps_found),
            "sitemapUrlsTotal": len(sitemap_urls),
            "internalEdges": sum(1 for e in graph_edges if e["kind"] != "external"),
            "externalDomains": len(external_domains),
            "externalEdges": sum(1 for e in graph_edges if e["kind"] == "external"),
            "localImagesDownloaded": downloader.downloaded_count if downloader else 0,
            "orphanPages": len(orphans),
            "unlistedPages": len(unlisted),
            "brokenOrRedirectPages": len(broken),
            "pagesWithSeoIssues": pages_with_seo_issues,
            "avgResponseTimeMs": avg_ttfb_ms,
            "medianResponseTimeMs": median_response_ms,
            "avgFetchDurationMs": avg_fetch_ms,
            "auditFindings": audit_summary["findings"],
            "auditFindingItems": audit_summary["findingItems"],
        },
        "siteIntel": site_intel_bundle,
        "linkHealth": link_health,
        "brandKit": brand_kit,
        "drift": drift,
        "robotsPolicy": robots_policy,
        "robotsPoliciesByOrigin": robots_policies,
        "sitemaps": sm_result.sitemaps_found,
        "sections": sections_summary,
        "nodes": graph_nodes,
        "edges": graph_edges,
    }

    manifest_path = os.path.join(site_root, "_site-graph.json")
    if not internal_only:
        manifest["stats"].pop("pagesWithSeoIssues", None)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Write _site-summary.json (complete structured site & brand intelligence for downstream tools)
    site_summary = {
        "captureStatus": capture_status,
        "captureWarnings": capture_warnings,
        "captureFindings": capture_findings[:200],
        "domain": clean_domain,
        "brandName": brand_name,
        "origin": origin,
        "capturedAt": captured_iso,
        "stats": manifest["stats"],
        "auditSummary": audit_summary,
        "audit": {k: v for k, v in audit.items() if k != "findings"},
        "findings": audit["findings"],
        "browserAudit": browser_result,
        "transport": transport,
        "linkHealth": link_health,
        "brandKit": brand_kit,
        "drift": drift,
        "robotsPolicy": robots_policy,
        "robotsPoliciesByOrigin": robots_policies,
        "resources": resources,
        "pipelineMetrics": collected["metrics"],
        "captureProvenance": provenance,
        "contacts": site_intel_bundle["contacts"],
        "techStack": stack_intel,
        "aiReadiness": ai_intel,
        "funnel": {
            **site_intel_bundle["funnel"],
            "videos": sorted(all_videos)[:50],
            "downloads": [{"url": k, "label": v} for k, v in sorted(all_downloads.items())][:50],
        },
        "schemaTypesUsed": all_schema_types,
        "homepageSchemas": root_schemas,
        "sections": sections_summary,
        "pages": [
            {
                "url": n["url"],
                "path": n["path"],
                "title": n["title"],
                "metaDescription": n["metaDescription"],
                "h1": n["h1"],
                "section": n["section"],
                "health": n["health"],
                "statusCode": n["statusCode"],
                "responseTimeMs": n["responseTimeMs"],
                "inSitemap": n["inSitemap"],
                "clickDepth": n["clickDepth"],
                "wordCount": n["wordCount"],
                "readingTimeMin": n["readingTimeMin"],
                "lang": n["lang"],
                "author": n["author"],
                "publishedDate": n["publishedDate"],
                "modifiedDate": n["modifiedDate"],
                "schemaTypes": n["schemaTypes"],
                "seoIssues": n["seoIssues"],
                "obsidianPath": n["obsidianPath"],
            }
            for n in internal_only
        ],
        "externalDomains": [
            {
                "domain": ed["domain"],
                "linkingPages": len(ed["source_urls"]),
                "totalMentions": len(ed["occurrences"]),
                "sampleUrls": sorted(ed["urls"])[:12],
                "obsidianPath": ext_note_by_domain.get(ed["domain"], ""),
            }
            for ed in sorted_ext_domains
        ],
    }
    with open(os.path.join(site_root, "_site-summary.json"), "w", encoding="utf-8") as f:
        json.dump(site_summary, f, indent=2, ensure_ascii=False)

    canvas_data = generate_sitemap_canvas(graph_nodes, graph_edges)
    with open(os.path.join(site_root, "_sitemap.canvas"), "w", encoding="utf-8") as f:
        json.dump(canvas_data, f, indent=2, ensure_ascii=False)

    base_yaml = build_pages_base_yaml(domain_folder, clean_domain, captured_iso)
    with open(os.path.join(site_root, "_pages.base"), "w", encoding="utf-8") as f:
        f.write(base_yaml)

    schema_rollup = {"organizations": [], "offersAndProducts": [], "people": [], "faqs": []}
    for record in page_records:
        for key in schema_rollup:
            schema_rollup[key].extend(record["extracted"].get("schema_entities", {}).get(key, []))
    write_evidence_pack(site_root, domain_folder, clean_domain, brand_name, origin, captured_iso,
        stack_intel, brand_kit, site_intel_bundle["contacts"], {"ctas": [cta for p in page_records for cta in p["extracted"].get("ctas", [])]}, schema_rollup,
        fetch_rows=fetch_rows, page_records=page_records, capture_status=capture_status)

    # Write rich executive _dashboard.md
    analytics_names = [t["name"] for t in stack_intel["analyticsAndPixels"]]
    cms_names = ", ".join(stack_intel["cmsOrFramework"])
    cdn_names = ", ".join(stack_intel["hostingAndCdn"]) or "Direct / Unspecified"
    sec_present = ", ".join(stack_intel["securityHeaders"]["present"]) or "None"
    sec_missing = ", ".join(stack_intel["securityHeaders"]["missing"]) or "None"
    sec_consistency = stack_intel["securityHeaders"]["consistency"]
    sec_inconsistent = ", ".join(sec_consistency["inconsistent"]) or "None"

    dash_lines = [
        "---",
        f"title: {yaml_quote(f'{brand_name} ({clean_domain}) - Site Intelligence Overview')}",
        f"site: {yaml_quote(clean_domain)}",
        f"brand: {yaml_quote(brand_name)}",
        f"captured_at: {yaml_quote(captured_iso)}",
        "tags:",
        "  - web-obs",
        "  - web-obs/dashboard",
        "---",
        "",
        f"# {brand_name} ({clean_domain})",
        "",
        f"- **Origin:** {origin}",
        f"- **Capture engine:** `{provenance['engineSha256']}`. Settings and runtime versions are in `_site-graph.json` and `_site-summary.json`.",
        f"- **Technology sample:** {len(html_samples)} of {stack_intel['coverage']['capturedHtmlPages']} HTML pages. {stack_intel['coverage']['selection']}. Security headers are read from the homepage and compared across the sampled pages.",
        f"- **Captured:** `{captured_iso}` (`{manifest['elapsedSec']}s`, avg final-request duration `{avg_ttfb_ms} ms` (median `{median_response_ms} ms`; redirect hops excluded))",
        f"- **Pages Crawled:** `{manifest['stats']['pagesCrawled']}` (from `{manifest['stats']['sitemapUrlsTotal']}` sitemap URLs across `{manifest['stats']['sitemapsFound']}` sitemap file(s))",
        f"- **Local Assets Saved:** `{manifest['stats']['localImagesDownloaded']}` (`{site_intel_bundle['totalAssetsMb']} MB`)",
        f"- **External Domains Linked:** `{manifest['stats']['externalDomains']}`",
        f"- **Visual Views:** Open **Web-Obs 3D Site Globe** from the left ribbon, or open [[sites/{domain_folder}/_sitemap.canvas|Visual Sitemap Canvas]] and [[sites/{domain_folder}/_pages.base|Pages Database]].",
        "",
        "## Saved Evidence & Link Checks",
        "",
        f"- [[sites/{domain_folder}/_fetch-log|Fetch receipts]] and [[sites/{domain_folder}/_evidence-pack|Website evidence package]]",
        f"- [[sites/{domain_folder}/_resources|Media and resources]]: {len(resources)} observed resources, separate from HTML pages.",
        f"- [[sites/{domain_folder}/_link-health|Link and resource checks]]: {link_health['checkedCount']}/{link_health['totalCount']} attempted; {link_health['uncheckedCount']} unchecked; {len(link_health['brokenLinks'])} confirmed 404/410 targets.",
        f"- Internal authority is a relative weighted link heuristic, not search-engine authority.",
        *([f"- [[sites/{domain_folder}/_drift-report|Changes since previous capture]]"] if drift else []),
        f"- [[sites/{domain_folder}/_audit|Site audit]]: {audit_summary['findings']} findings over {audit_summary['findingItems']} items, {audit_summary['linkOpportunities']} internal link opportunities, {audit_summary['linkFixes']} internal links to fix.",
        *([f"- [[sites/{domain_folder}/_tasks|Task list]]: {task_counts['open']} open, {task_counts['resolvedNow']} resolved in this capture."] if task_counts else []),
        "",
        "## Collection Coverage",
        "",
        f"- **Status:** {capture_status}",
        *[f"- {warning}" for warning in capture_warnings],
        "- Public-page observations only. No AI or external enrichment API integrations.",
        "",
        "## Tech Stack, Analytics & Security",
        "",
        f"- **CMS / Framework:** {cms_names}",
        f"- **Hosting / CDN:** {cdn_names}",
        f"- **Analytics & Pixels:** {', '.join(analytics_names) if analytics_names else 'None detected in static HTML'}",
    ]
    if stack_intel["measurementIds"]["ga4"] or stack_intel["measurementIds"]["gtm"]:
        ids_joined = ", ".join(stack_intel["measurementIds"]["ga4"] + stack_intel["measurementIds"]["gtm"])
        dash_lines.append(f"- **Measurement / Container IDs:** `{ids_joined}`")
    dash_lines.extend(
        [
            f"- **Security Headers Present:** {sec_present}",
            f"- **Security Headers Missing:** {sec_missing}",
            f"- **Security Headers Inconsistent Across {sec_consistency['sampledPages']} Sampled Pages:** {sec_inconsistent}",
            *[f"- **Header note:** {note}" for note in sec_consistency["notes"]],
        ]
    )
    dash_lines.append("")

    dash_lines.extend(
        [
            "## AI Search & Agent Readiness (GEO)",
            "",
            f"- **llms.txt:** `{'Present (saved locally)' if ai_intel['endpoints']['llmsTxt'] else 'Missing'}` | **llms-full.txt:** `{'Present (saved locally)' if ai_intel['endpoints']['llmsFullTxt'] else 'Missing'}` | **ai-catalog.json:** `{'Present' if ai_intel['endpoints']['aiCatalogJson'] else 'Not found'}`",
            f"- **Validation:** {_validation_summary(ai_intel)}",
            f"- **Sitemap hygiene:** {_hygiene_summary(ai_intel.get('sitemapHygiene') or {})}",
            f"- **AI Crawlers Allowed in robots.txt:** `{ai_intel['allowedAiBotsCount']}/{len(ai_intel['aiBotsPolicy'])}`"
            + (f" (Blocked: `{', '.join(ai_intel['blockedAiBots'])}`)" if ai_intel["blockedAiBots"] else " (All major AI search & training bots allowed)"),
            "",
        ]
    )

    dash_lines.extend(
        [
            "## Brand, Contacts & Conversion Funnel",
            "",
            f"- **Emails:** {', '.join(f'`{e}`' for e in site_intel_bundle['contacts']['emails']) or 'None found'}",
            f"- **Phones:** {', '.join(f'`{p}`' for p in site_intel_bundle['contacts']['phones']) or 'None found'}",
            f"- **Social Profiles:** {', '.join(site_intel_bundle['contacts']['socialProfiles'][:10]) or 'None found'}",
            f"- **Forms Across Site:** `{total_forms}` | **Embedded/Linked Videos:** `{len(all_videos)}` | **Downloadable Assets:** `{len(all_downloads)}`",
        ]
    )
    if funnel_platforms:
        plat_summary = ", ".join(f"{fp['platform']} ({fp['category']})" for fp in funnel_platforms)
        dash_lines.append(f"- **Booking / Community / Checkout Platforms:** {plat_summary}")
    if all_schema_types:
        dash_lines.append(f"- **Schema.org Types (`{len(all_schema_types)}`):** `{', '.join(all_schema_types)}`")
    dash_lines.append("")

    if orphans:
        dash_lines.extend(["## Orphan Pages (In Sitemap, Zero Incoming Internal Links)", ""])
        for n in orphans:
            dash_lines.append(f"- [[{n['obsidianPath'][:-3]}|{n['title']}]] (`{n['path']}`)")
        dash_lines.append("")

    if unlisted:
        dash_lines.extend(["## Unlisted Pages (Linked Internally, Missing from Sitemap)", ""])
        for n in unlisted:
            dash_lines.append(f"- [[{n['obsidianPath'][:-3]}|{n['title']}]] (`{n['path']}`)")
        dash_lines.append("")

    if broken:
        dash_lines.extend(["## Broken or Redirected Pages", ""])
        for n in broken:
            dash_lines.append(
                f"- [[{n['obsidianPath'][:-3]}|{n['title']}]] (`{n['path']}`, HTTP `{n['statusCode']}`)"
            )
        dash_lines.append("")

    flagged_pages = [n for n in internal_only if n.get("seoIssues")]
    if flagged_pages:
        dash_lines.extend([f"## On-Page SEO Audit Signals ({len(flagged_pages)} page(s))", ""])
        for n in flagged_pages[:30]:
            issues_str = ", ".join(f"`{i}`" for i in n["seoIssues"])
            dash_lines.append(f"- [[{n['obsidianPath'][:-3]}|{n['title']}]] (`{n['path']}`): {issues_str}")
        dash_lines.append("")

    dash_lines.extend(["## Site Sections", ""])
    for sec_item in sections_summary:
        dash_lines.append(f"- **{sec_item['label']}**: `{sec_item['pageCount']}` page(s)")
    dash_lines.append("")

    with open(os.path.join(site_root, "_dashboard.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(dash_lines))

    with open(os.path.join(site_root, "_robots-policies.json"), "w", encoding="utf-8") as f:
        json.dump(robots_policies, f, indent=2, ensure_ascii=False)

    # Include compilation and exports in the saved elapsed time.
    manifest["elapsedSec"] = round(time.time() - started_at, 2)
    manifest["pipelineMetrics"]["captureBeforePromotionSec"] = manifest["elapsedSec"]
    site_summary["pipelineMetrics"] = manifest["pipelineMetrics"]
    for name, value in (("_site-graph.json", manifest), ("_site-summary.json", site_summary)):
        with open(os.path.join(site_root, name), "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
    # Vault graph preferences belong to the member; capturing does not modify them.
    assert_engine_unchanged(provenance)
    return manifest


def crawl_website_to_vault(
    target_url: str,
    vault_dir: str,
    max_pages: int = 250,
    download_images: bool = True,
    render_mode: str = "auto",
    delay_sec: float = 0.15,
    check_external: bool = True,
    parallel: bool = True,
    image_mode: str = "preferred",
    browser_audit: bool = True,
    spell_check: bool = False,
    dns_checks: bool = True,
    snapshot_limit: int = 25,
    snapshot_html: bool = False,
    tls_check: bool = True,
    tasks: bool = True,
    deadline_sec: Optional[float] = None,
) -> dict:
    from url_safety import set_capture_deadline
    # One deadline for every network phase. Writing the notes and saving the capture still finish.
    set_capture_deadline(time.monotonic() + deadline_sec if deadline_sec else None)
    try:
        with CaptureTransaction(vault_dir) as transaction:
            manifest = _capture_to_staging(
                target_url, str(transaction.stage), max_pages, download_images,
                render_mode, delay_sec, previous_vault_dir=vault_dir,
                check_external=check_external, parallel=parallel, image_mode=image_mode,
                browser_audit=browser_audit, spell_check=spell_check, dns_checks=dns_checks,
                snapshot_limit=snapshot_limit, snapshot_html=snapshot_html,
                tls_check=tls_check, tasks=tasks, deadline_sec=deadline_sec,
            )
            emit_event("phase", phase="compile", message="Validating and saving notes, media inventory and map...")
            manifest = transaction.commit(manifest)
    finally:
        set_capture_deadline(None)
    emit_event(
        "complete", captureStatus=manifest.get("captureStatus", "partial"),
        siteId=manifest["siteId"], domain=manifest["domain"],
        brandName=manifest.get("brandName", manifest["domain"]),
        manifestPath=f"sites/{manifest['siteId']}/_site-graph.json",
        dashboardPath=f"sites/{manifest['siteId']}/_dashboard.md",
        stats=manifest["stats"],
    )
    return manifest


def _cancel_capture(_signum, _frame) -> None:
    raise KeyboardInterrupt("Capture cancelled.")


def main() -> int:
    signal.signal(signal.SIGTERM, _cancel_capture)
    parser = argparse.ArgumentParser(
        description="Crawl a website (sitemap first, full content, local assets, analytics & link graph) into an Obsidian vault."
    )
    parser.add_argument("url", help="Website URL or domain to capture")
    parser.add_argument("--vault", default=".", help="Path to target Obsidian vault root")
    parser.add_argument("--continue-links", action="store_true", help="Check remaining saved targets; positional argument is a saved site ID")
    parser.add_argument("--image-mode", choices=("preferred", "all"), default="preferred", help="Download primary images or all observed variants")
    parser.add_argument("--serial", action="store_true", help="Use sequential workers for reproducible comparisons")
    parser.add_argument("--no-check-external", action="store_true", help="Record external URLs without requesting their destinations")
    parser.add_argument("--no-browser-audit", action="store_true", help="Skip the sampled browser audit (lab timings, axe, screenshots)")
    parser.add_argument("--spell-check", action="store_true", help="Check English spelling (needs pyspellchecker)")
    parser.add_argument("--no-dns-checks", action="store_true", help="Skip email DNS checks through the system resolver")
    parser.add_argument("--no-snapshots", action="store_true", help="Skip full-page snapshots")
    parser.add_argument("--snapshot-limit", type=int, default=25, help="Most pages to snapshot, most important first (default: 25)")
    parser.add_argument("--snapshot-html", action="store_true", help="Also save the rendered HTML next to each snapshot")
    parser.add_argument("--no-tls-check", action="store_true", help="Skip the TLS certificate check (one handshake with the site)")
    parser.add_argument("--no-tasks", action="store_true", help="Do not write _tasks.md")
    parser.add_argument("--deadline", type=float, default=None, metavar="SECONDS",
                        help="One time limit for every network phase of the capture; phases that hit it are marked partial")
    parser.add_argument("--max-pages", type=int, default=250, help="Maximum pages to crawl (default: 250)")
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip downloading images locally into sites/<domain>/assets/",
    )
    parser.add_argument(
        "--render",
        choices=("auto", "always", "never"),
        default="auto",
        help="SPA rendering mode (default: auto)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Polite delay in seconds between page requests (default: 0.15)",
    )
    args = parser.parse_args()

    if args.deadline is not None and not (1 <= args.deadline <= 86400):
        emit_event("error", message="--deadline must be between 1 and 86400 seconds.")
        return 2
    vault_dir = os.path.abspath(args.vault)
    if not os.path.isdir(vault_dir):
        emit_event("error", message=f"Vault directory does not exist: {vault_dir}")
        return 1

    try:
        if args.continue_links:
            from link_recheck import continue_link_checks
            continue_link_checks(args.url, vault_dir, emit_event)
            return 0
        crawl_website_to_vault(
            target_url=args.url,
            vault_dir=vault_dir,
            max_pages=max(1, min(1000, args.max_pages)),
            download_images=not args.no_images, image_mode=args.image_mode,
            render_mode=args.render,
            check_external=not args.no_check_external, parallel=not args.serial,
            browser_audit=not args.no_browser_audit, spell_check=args.spell_check, dns_checks=not args.no_dns_checks,
            snapshot_limit=0 if args.no_snapshots else max(0, min(500, args.snapshot_limit)), snapshot_html=args.snapshot_html,
            delay_sec=max(0.0, min(10.0, args.delay)),
            tls_check=not args.no_tls_check, tasks=not args.no_tasks, deadline_sec=args.deadline,
        )
        return 0
    except KeyboardInterrupt:
        emit_event("cancelled", message="Capture cancelled.")
        return 130
    except Exception as exc:
        emit_event("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
