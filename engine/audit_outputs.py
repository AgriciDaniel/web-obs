"""Vault outputs for the site audit: report note, CSV export, persistent task list, page sections."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from issue_catalog import describe

_TASK_RE = re.compile(r"^- \[(?P<state>[ xX])\] (?P<body>.*?)\s*\^(?P<id>wo-[0-9a-f]{10})\s*$")
TASKS_FILE = "_tasks.md"


def _cell(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _stable_detail(detail) -> str:
    """Detail text without numbers, so counts and dates do not change a task's identity."""
    text = re.sub(r"\d+(?:\.\d+)?", "#", str(detail or "").lower())
    return re.sub(r"\s+", " ", text).strip()[:160]


def task_id(finding_id: str, target: dict) -> str:
    key = f"{finding_id}|{target.get('url', '')}|{target.get('sourceUrl', '')}|{_stable_detail(target.get('detail'))}"
    return "wo-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


# Which check has to run again before a missing finding counts as fixed.
_BROWSER_IDS = ("a11y-", "js-dependent-content", "slow-lab-lcp", "third-party-before-interaction")
_DNS_IDS = ("spf-", "dmarc-", "dkim-", "caa-")
_HEADER_IDS = ("hsts-", "csp-", "cookie-", "header-hygiene", "headers-missing", "securitytxt-")
_SITE_FILE_IDS = ("robots-syntax", "sitemap-limits", "crawl-traps")


def _rechecked(fid: str, url: str, source: str, ctx: dict) -> bool:
    if not fid:  # Task written before 0.2.0 markers carried the finding ID.
        return ctx["complete"] or url in ctx["okUrls"]
    if fid in ctx["truncated"]:
        return False  # Only the first items of this finding were kept, so absence proves nothing.
    if fid.startswith(_BROWSER_IDS):
        return url in ctx["browserUrls"]
    if fid.startswith("tls-"):
        return ctx["tls"]
    if fid.startswith(_DNS_IDS):
        return ctx["dns"]
    if fid.startswith(_HEADER_IDS):
        return ctx["headers"]
    if fid.startswith("llmstxt-"):
        # The llms.txt probe must have got an answer (found, absent or an HTML page). A link task also needs that
        # link answered this time: a link the direct checks did not reach proves nothing.
        if not ctx.get("llms", False):
            return False
        if fid in ("llmstxt-dead-links", "llmstxt-link-hygiene"):
            return url not in ctx.get("llmsUncheckedLinks", set())
        return True
    if fid.startswith(_SITE_FILE_IDS):
        return ctx["robots"] if fid == "robots-syntax" else ctx["complete"]
    key = source or url
    if key in ctx["pageUrls"]:
        return key in ctx["okUrls"]
    return ctx["complete"]


def page_findings(nodes: list[dict]) -> list[dict]:
    """Turn per-page issue slugs into findings in the shared shape."""
    grouped: dict[str, dict] = {}
    for node in nodes:
        for issue in node.get("seoIssues") or []:
            info = describe(issue)
            row = grouped.setdefault(info["slug"], {
                "id": f"seo:{info['slug']}", "category": info["category"], "tone": info["tone"], "title": info["title"],
                "explanation": info["explanation"], "targets": []})
            detail = f"{info['count']} on this page" if info["count"] else ""
            row["targets"].append({"url": node["url"], "detail": detail})
    for row in grouped.values():
        row["targetCount"] = len(row["targets"])
    return list(grouped.values())


def drift_findings(drift: Optional[dict]) -> list[dict]:
    if not drift:
        return []
    out = []

    def add(fid, tone, title, explanation, targets):
        if targets:
            out.append({"id": fid, "category": "changes", "tone": tone, "title": title, "explanation": explanation,
                        "targets": targets[:200], "targetCount": len(targets)})
    add("change-noindex-added", "attention", "Pages became noindex since the last capture",
        "These pages now ask search engines not to index them.", [{"url": r["url"], "detail": f"{r.get('old') or 'none'} to {r.get('new')}"} for r in drift.get("noindexAdded", [])])
    add("change-canonical", "review", "Canonical changed since the last capture", "Check that the new canonical is intended.",
        [{"url": r["url"], "detail": f"{r.get('old') or 'none'} to {r.get('new') or 'none'}"} for r in drift.get("canonicalChanges", [])])
    add("change-title", "review", "Title changed since the last capture", "Titles affect how the page appears in search results.",
        [{"url": r["url"], "detail": f"\"{r.get('old')}\" to \"{r.get('new')}\""} for r in drift.get("titleChanges", [])])
    add("change-description", "review", "Meta description changed since the last capture", "Observed change only.",
        [{"url": r["url"], "detail": "Description text changed"} for r in drift.get("descriptionChanges", [])])
    add("change-schema-removed", "attention", "Structured data removed since the last capture", "Removed markup can cost rich results.",
        [{"url": r["url"], "detail": "Removed: " + ", ".join(r["removed"])} for r in drift.get("schemaChanges", []) if r.get("removed")])
    add("change-new-issues", "review", "New page issues since the last capture", "Issues that were not recorded on the previous capture.",
        [{"url": r["url"], "detail": ", ".join(r["added"])} for r in drift.get("issueChanges", []) if r.get("added")])
    add("change-health", "attention", "Pages that started failing since the last capture", "The page answered with an error this time.",
        [{"url": r["url"], "detail": f"HTTP {r.get('oldStatus')} to {r.get('newStatus')}"} for r in drift.get("healthChanges", [])
         if isinstance(r.get("newStatus"), int) and r["newStatus"] >= 400 and not (isinstance(r.get("oldStatus"), int) and r["oldStatus"] >= 400)])
    add("change-files", "review", "Site files changed since the last capture", "robots.txt, llms.txt or security.txt differ from the previous capture.",
        [{"url": r["file"], "detail": f"{r['added']} lines added, {r['removed']} removed"} for r in drift.get("fileChanges", [])])
    add("change-headers", "review", "Security headers changed since the last capture", "Headers on the homepage differ from the previous capture.",
        [{"url": drift.get("homeUrl") or "", "detail": ("Added: " + ", ".join(r["added"]) if r.get("added") else "") + (" Removed: " + ", ".join(r["removed"]) if r.get("removed") else "")}
         for r in [drift.get("headerChanges") or {}] if r.get("added") or r.get("removed")])
    return out


def security_txt_findings(ai_intel: dict, origin: str, today: date) -> list[dict]:
    expires = ((ai_intel.get("validation") or {}).get("securityTxt") or {}).get("expires")
    if not expires:
        return []
    try:
        when = datetime.fromisoformat(str(expires).replace("Z", "+00:00")).date()
    except ValueError:
        return []
    days = (when - today).days
    if days > 30:
        return []
    title = "security.txt has expired" if days < 0 else f"security.txt expires in {days} days"
    return [{"id": "securitytxt-expiry", "category": "security", "tone": "attention" if days < 0 else "review", "title": title,
             "explanation": "RFC 9116 requires a future Expires date. Update the file before it lapses.",
             "targets": [{"url": origin.rstrip("/") + "/.well-known/security.txt", "detail": f"Expires {when.isoformat()}"}], "targetCount": 1}]


def write_findings_csv(site_root: str, findings: list[dict]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["category", "tone", "finding", "url", "source_url", "detail", "task_id"])
    for f in findings:
        for t in f["targets"]:
            writer.writerow([f["category"], f["tone"], f["title"], t.get("url", ""), t.get("sourceUrl", ""), t.get("detail", ""), task_id(f["id"], t)])
    Path(site_root, "_findings.csv").write_text(buf.getvalue(), encoding="utf-8")


def _read_previous_tasks(previous_site_root: Optional[str]) -> dict[str, dict]:
    if not previous_site_root:
        return {}
    path = Path(previous_site_root, TASKS_FILE)
    if not path.is_file():
        return {}
    rows = {}
    section = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        m = _TASK_RE.match(line.strip())
        if m:
            rows[m.group("id")] = {"checked": m.group("state").lower() == "x", "body": m.group("body"), "section": section}
    return rows


def write_tasks(site_root: str, previous_site_root: Optional[str], findings: list[dict], captured_iso: str,
                captured_urls: set[str], capture_complete: bool, note_by_url: dict, *, ok_urls: Optional[set] = None,
                checks_ran: Optional[dict] = None) -> dict:
    """Write _tasks.md, keeping ticks and closing a task only when its check ran again and no longer finds it."""
    previous = _read_previous_tasks(previous_site_root)
    day = captured_iso[:10]
    ran = checks_ran or {}
    ctx = {"complete": capture_complete, "pageUrls": set(captured_urls),
           "okUrls": set(captured_urls if ok_urls is None else ok_urls),
           "truncated": {f["id"] for f in findings if f.get("targetCount", len(f["targets"])) > len(f["targets"])},
           "browserUrls": set(ran.get("browserUrls") or ()), "tls": bool(ran.get("tls")), "dns": bool(ran.get("dns")),
           "headers": bool(ran.get("headers")), "robots": bool(ran.get("robots"))}
    current_ids = set()
    open_lines, new_resolved, old_resolved, carried_lines = [], [], [], []
    counts = {"open": 0, "ticked": 0, "resolved": 0, "resolvedNow": 0, "notRechecked": 0}
    order = {"attention": 0, "review": 1, "coverage": 2}
    for f in sorted(findings, key=lambda f: (order.get(f["tone"], 3), f["category"], f["title"])):
        if f["tone"] == "coverage" or f["category"] == "changes":
            continue  # Collection gaps and change notices are not work items.
        block = []
        for t in f["targets"]:
            tid = task_id(f["id"], t)
            if tid in current_ids:
                continue
            current_ids.add(tid)
            url, source = t.get("url", ""), t.get("sourceUrl", "")
            note = note_by_url.get(source or url)
            where = f"[[{note[:-3]}]]" if note else (source or url)
            detail = re.sub(r"\s+", " ", str(t.get("detail") or "")).strip()
            detail = f": {detail}" if detail else ""
            prior = previous.get(tid)
            ticked = bool(prior and prior["checked"] and prior["section"] != "resolved")
            suffix = " (ticked, still observed)" if ticked else ""
            block.append(f"- [{'x' if ticked else ' '}] {where}{detail}{suffix} %%{url}|{source}|{f['id']}%% ^{tid}")
            counts["ticked" if ticked else "open"] += 1
        if block:
            open_lines += [f"### {f['title']}", "", *block, ""]
    for tid, prior in previous.items():
        if tid in current_ids:
            continue
        marker = re.search(r"%%(\S*)%%", prior["body"])
        parts = (marker.group(1).split("|") + ["", ""])[:3] if marker else ["", "", ""]
        url, source, fid = parts
        body = re.sub(r"\s*%%\S*%%", "", prior["body"])
        body = re.sub(r"\s*\((?:ticked, still observed|resolved [^)]*|not rechecked[^)]*)\)", "", body).strip()
        body = re.sub(r"^~~(.*)~~$", r"\1", body)
        keep = f" %%{marker.group(1)}%%" if marker else ""
        if prior["section"] == "resolved":
            old_resolved.append(f"- [x] {prior['body']} ^{tid}")
            counts["resolved"] += 1
            continue
        if _rechecked(fid, url, source, ctx):
            new_resolved.append(f"- [x] ~~{body}~~ (resolved {day}){keep} ^{tid}")
            counts["resolved"] += 1
            counts["resolvedNow"] += 1
        else:
            carried_lines.append(f"- [{'x' if prior['checked'] else ' '}] {body} (not rechecked {day}){keep} ^{tid}")
            counts["notRechecked"] += 1
    lines = ["---", "tags:", "  - web-obs", "  - web-obs/tasks", f"updated: \"{captured_iso}\"", "---", "",
             "# Site tasks", "",
             "Generated from the capture findings. Tick items as you fix them. Ticks are kept on the next capture,",
             "and a task closes automatically when the check that found it runs again and no longer finds it.",
             "Do not edit the `^wo-` ids or the hidden markers; they link each task to its finding.",
             "Edits made while a capture is running are replaced when it finishes.", "",
             f"Open: {counts['open']}. Ticked but still observed: {counts['ticked']}. Resolved in this capture: {counts['resolvedNow']}.", "",
             "## Open", "", *(open_lines or ["Nothing open.", ""])]
    if carried_lines:
        lines += ["## Not rechecked", "", "The check behind these tasks did not run again on this capture, so they stay as they were.", "", *carried_lines, ""]
    resolved_lines = (new_resolved + old_resolved)[:500]
    lines += ["## Resolved", "", *(resolved_lines or ["Nothing resolved yet."]), ""]
    Path(site_root, TASKS_FILE).write_text("\n".join(lines), encoding="utf-8")
    return counts


def page_audit_section(url: str, node: dict, findings_by_url: dict, checks: Optional[dict], browser_page: Optional[dict],
                       domain_folder: Optional[str] = None) -> list[str]:
    lines = ["## Page Audit", ""]
    issues = node.get("seoIssues") or []
    if issues:
        for issue in issues:
            info = describe(issue)
            count = f" ({info['count']})" if info["count"] else ""
            lines.append(f"- **{info['title']}**{count}: {info['explanation']}")
    for f, t in findings_by_url.get(url, [])[:25]:
        detail = f": {t['detail']}" if t.get("detail") else ""
        lines.append(f"- **{f['title']}**{detail}")
    if len(lines) == 2:
        lines.append("No page issues recorded.")
    if checks:
        lines += ["", "| Measure | Value |", "| :--- | :--- |"]
        rd = checks.get("readability") or {}
        rows = [("Text to HTML ratio", f"{round((checks.get('textRatio') or 0) * 100, 1)}%"),
                ("DOM elements / depth", f"{checks['dom']['nodes']} / {checks['dom']['maxDepth']}"),
                ("Render-blocking", f"{len(checks['scripts']['renderBlocking'])} scripts, {len(checks['stylesheets']['renderBlocking'])} stylesheets")]
        if rd:
            rows.insert(1, ("Flesch reading ease / grade", f"{rd['fleschReadingEase']} / {rd['fleschKincaidGrade']}"))
        cit = checks.get("citability") or {}
        if cit:
            rows.append(("Question headings / lists / tables", f"{cit['questionHeadings']} / {cit['lists']} / {cit['tables']}"))
        lines += [f"| {a} | {_cell(b)} |" for a, b in rows]
    if browser_page and not browser_page.get("error"):
        lab = browser_page.get("lab") or {}
        a11y = browser_page.get("a11y") or {}
        lines += ["", f"Browser sample: LCP {lab.get('lcpMs', 'n/a')} ms, CLS {lab.get('cls', 'n/a')}, "
                  f"{len(a11y.get('violations') or [])} axe rule violations. {lab.get('note', '')}"]
        if browser_page.get("screenshot"):
            # A full vault path, so Obsidian never has to guess between sites with similar file names.
            shot = browser_page["screenshot"]
            lines += ["", f"![[{f'sites/{domain_folder}/{shot}' if domain_folder else shot}|Screenshot]]"]
    lines.append("")
    return lines


_LLMS_PROBE_TEXT = {"absent": "Not found.", "html": "The address serves a web page instead of a markdown file.",
                    "refused": "Not checked: robots.txt does not allow fetching it.", "unavailable": "Not checked: the site answered with an error.",
                    "not-checked": "Not checked."}


def _llms_section(llms: dict, domain_folder: str) -> list[str]:
    probe = llms.get("probe") or {}
    if not probe:
        return []
    lines = ["## llms.txt", "", "Checked against the [llmstxt.org](https://llmstxt.org/) format. Its links are matched against this capture."]
    draft = llms.get("draftPath")
    draft_link = f"[[{draft.removesuffix('.md')}|llms.txt draft built from this capture]]" if draft else None
    if probe.get("state") != "found":
        lines += ["", f"- {_LLMS_PROBE_TEXT.get(probe.get('state'), 'Not checked.')} {probe.get('detail') or ''}".rstrip()]
        if draft_link:
            lines.append(f"- {draft_link}")
        return lines + [""]
    v = llms.get("validation") or {}
    stats = v.get("stats") or {}
    lines += ["", f"- **Title:** {v.get('title') or 'missing'}", f"- **Summary:** {v.get('summary') or 'missing'}",
              f"- **Sections:** {', '.join(s['name'] for s in v.get('sections') or []) or 'none'}" + (" (with Optional)" if v.get("hasOptional") else ""),
              f"- **Links:** {stats.get('links', 0)} ({stats.get('sameSiteLinks', 0)} on this site, {stats.get('externalLinks', 0)} elsewhere, "
              f"{stats.get('markdownLinks', 0)} to markdown, {stats.get('linksWithNotes', 0)} with notes)",
              f"- **Size:** {stats.get('bytes', 0):,} bytes, about {stats.get('approxTokens', 0):,} tokens"]
    if draft_link:
        lines.append(f"- {draft_link}")
    notes = v.get("notes") or []
    if notes:
        lines += ["", "| Line | Level | Note |", "| :--- | :--- | :--- |"]
        lines += [f"| {n['line'] or ''} | {n['level']} | {n['message'].replace('|', '/')} |" for n in notes[:60]]
    rows = [r for r in llms.get("links") or [] if r["state"] not in ("ok", "external")]
    if rows:
        lines += ["", "| Line | Link | Result |", "| :--- | :--- | :--- |"]
        lines += [f"| {r['line']} | {r['url']} | {r['state']}: {r['detail'].replace('|', '/')} |" for r in rows[:100]]
    return lines + [""]


def write_audit_report(site_root: str, domain_folder: str, clean_domain: str, captured_iso: str, audit: dict,
                       note_by_url: dict, transport: dict, browser: dict, tasks: Optional[dict], llms: Optional[dict] = None) -> None:
    def link(url):
        note = note_by_url.get(url)
        return f"[[{note[:-3]}]]" if note else url

    lines = ["---", "tags:", "  - web-obs", "  - web-obs/audit", f"captured_at: \"{captured_iso}\"", "---", "",
             f"# Site Audit: {clean_domain}", "",
             "Observations from one capture. Uncaptured pages can change any result. This is not a combined score.", "",
             *([f"- [[sites/{domain_folder}/_tasks|Task list]]: {tasks.get('open', 0)} open, {tasks.get('resolvedNow', 0)} resolved in this capture."] if tasks else []),
             f"- `_findings.csv` holds every finding row for spreadsheets.", ""]
    order = {"attention": 0, "review": 1, "coverage": 2}
    findings = sorted(audit["findings"], key=lambda f: (order.get(f["tone"], 3), -f.get("targetCount", len(f["targets"]))))
    lines += ["## Findings", "", "| Finding | Category | Items |", "| :--- | :--- | :--- |"]
    lines += [f"| {_cell(f['title'])} | {f['category']} | {f.get('targetCount', len(f['targets']))} |" for f in findings]
    lines.append("")
    if audit["linkOpportunities"]:
        lines += ["## Internal Link Opportunities", "", "Heuristic: the source page mentions the target page's title or H1 but does not link to it.", "",
                  "| On this page | Mentions | Link to |", "| :--- | :--- | :--- |"]
        lines += [f"| {link(r['sourceUrl'])} | {_cell(r['phrase'])} | {link(r['targetUrl'])} |" for r in audit["linkOpportunities"][:150]]
        lines.append("")
    if audit["linkFixes"]:
        lines += ["## Internal Link Fix List", "", "| Fix on page | Linked URL | Problem | Use instead |", "| :--- | :--- | :--- | :--- |"]
        lines += [f"| {link(r['sourceUrl'])} | {_cell(r['linkedUrl'])} | {r['problem']} | {_cell(r['targetUrl'])} |" for r in audit["linkFixes"][:300]]
        lines.append("")
    dup = audit["duplicates"]
    if dup["titles"] or dup["descriptions"] or dup["exactContent"] or dup["nearContent"]:
        lines += ["## Duplicates", ""]
        for label, key in (("Same title", "titles"), ("Same description", "descriptions"), ("Same H1", "h1")):
            for g in dup[key][:40]:
                lines.append(f"- **{label}** \"{_cell(g['value'][:80])}\": " + ", ".join(link(u) for u in g["urls"][:8]))
        for g in dup["exactContent"][:40]:
            lines.append("- **Identical content**: " + ", ".join(link(u) for u in g["urls"][:8]))
        for g in dup["nearContent"][:40]:
            lines.append(f"- **Near duplicate ({round(g['similarity'] * 100)}%)**: " + ", ".join(link(u) for u in g["urls"]))
        lines.append("")
    if audit["cannibalization"]:
        lines += ["## Pages Competing for One Topic", ""]
        lines += [f"- \"{_cell(r['term'])}\": " + ", ".join(link(u) for u in r["urls"][:8]) for r in audit["cannibalization"][:60]]
        lines.append("")
    kw = audit["keywords"]
    if kw["bigrams"]:
        lines += ["## Top Phrases Across the Site", "", "| Phrase | Uses | Pages |", "| :--- | :--- | :--- |"]
        lines += [f"| {_cell(r['term'])} | {r['count']} | {r['pages']} |" for r in (kw["bigrams"][:10] + kw["trigrams"][:5])]
        lines.append("")
    fresh = audit["freshness"]
    lines += ["## Freshness and Trust", "",
              f"- Dated pages: {fresh['datedCount']}. Undated: {fresh['undatedCount']}. Older than {fresh['staleAfterDays']} days: {len(fresh['stale'])}."]
    trust = audit["trust"]
    for label, key in (("About", "about"), ("Contact", "contact"), ("Privacy", "privacy"), ("Terms", "terms")):
        lines.append(f"- {label}: {link(trust[key]) if trust[key] else 'not found in this capture'}")
    lines += [f"- Pages with an author byline: {trust['pagesWithAuthor']} of {trust['pagesChecked']}. {trust['note']}", ""]
    contrast = audit.get("paletteContrast") or {}
    if contrast.get("colors"):
        lines += ["## Palette Contrast", "", contrast["note"], "", "| Color | On white | On black |", "| :--- | :--- | :--- |"]
        lines += [f"| `{c['color']}` | {c['onWhite']}:1 | {c['onBlack']}:1 |" for c in contrast["colors"]]
        aa_pairs = [p for p in contrast["pairs"] if p["aaText"]][:10]
        if aa_pairs:
            lines += ["", "Palette pairs that reach 4.5:1: " + ", ".join(f"`{p['a']}` on `{p['b']}` ({p['ratio']}:1)" for p in aa_pairs)]
        lines.append("")
    lines += _llms_section(llms or {}, domain_folder)
    tls = (transport or {}).get("tls") or {}
    if tls:
        lines += ["## Certificate and Email Security", "",
                  f"- **TLS:** {tls.get('state')}. {tls.get('detail', '')}" + (f" Expires {tls.get('notAfter')} ({tls.get('daysRemaining')} days)." if tls.get("notAfter") else "")]
        email = (transport or {}).get("emailDns") or {}
        if email:
            lines.append(f"- **Email DNS:** {email.get('state')}. {email.get('detail', '')}")
        lines.append("")
    if browser and browser.get("pages"):
        lines += ["## Browser Sample", "", browser.get("detail", ""), "",
                  "| Page | LCP ms | CLS | Words added by JS | axe violations | Third-party hosts |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
        for p in browser["pages"]:
            if p.get("error"):
                lines.append(f"| {link(p['url'])} | {_cell(p['error'])} | | | | |")
                continue
            lab, gap, a11y, tp = p.get("lab") or {}, p.get("jsGap") or {}, p.get("a11y") or {}, p.get("thirdParty") or {}
            lines.append(f"| {link(p['url'])} | {lab.get('lcpMs', '')} | {lab.get('cls', '')} | {gap.get('wordsAddedByJsPct', '')}% | "
                         f"{len(a11y.get('violations') or [])} | {len(tp.get('hosts') or [])} |")
        lines += ["", "Lab numbers come from one load on this machine through the capture proxy. They are not field data or Core Web Vitals.", ""]
    Path(site_root, "_audit.md").write_text("\n".join(lines), encoding="utf-8")
