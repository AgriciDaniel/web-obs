#!/usr/bin/env python3
"""Read-only saved-capture integrity checks. No network or engine imports."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse

SHA256 = re.compile(r"[0-9a-fA-F]{64}")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".bmp", ".ico", ".tif", ".tiff"}
CAPTION_EXTENSIONS = {".vtt", ".srt", ".ttml", ".dfxp", ".sbv", ".ass", ".ssa"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | CAPTION_EXTENSIONS | {
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus",
    ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".ogv", ".m3u8", ".mpd",
    ".pdf", ".zip", ".gz", ".woff", ".woff2", ".ttf", ".otf",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_signature(data):
    head = data.lstrip()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:].lstrip()
    for prefix, name in ((b"\x89PNG\r\n\x1a\n", "PNG"), (b"\xff\xd8\xff", "JPEG"),
                         (b"GIF87a", "GIF"), (b"GIF89a", "GIF"), (b"%PDF-", "PDF"),
                         (b"ID3", "MP3"), (b"fLaC", "FLAC"), (b"OggS", "Ogg"),
                         (b"\x1aE\xdf\xa3", "WebM/Matroska"), (b"WEBVTT", "WebVTT"),
                         (b"wOFF", "WOFF"), (b"wOF2", "WOFF2"), (b"OTTO", "OpenType")):
        if head.startswith(prefix):
            return name
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "MP4/AVIF container"
    if data[:4] == b"RIFF" and data[8:12] in (b"WAVE", b"WEBP", b"AVI "):
        return "RIFF media"
    if re.match(rb"(?:<\?xml[^>]*>\s*)?<(?:svg|tt)(?:\s|>)", head, re.I):
        return "SVG/TTML"
    if re.match(rb"(?:\xef\xbb\xbf)?\d+\r?\n\d\d:\d\d:\d\d[,\.]\d+\s+-->", head):
        return "SRT captions"
    return None


def markdown_without_code(text):
    """Ignore literal examples while preserving line offsets for diagnostics."""
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence is None and match:
            fence = (match.group(1)[0], len(match.group(1)))
            lines.append("\n" if line.endswith("\n") else "")
        elif fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1]:
                fence = None
            lines.append("\n" if line.endswith("\n") else "")
        else:
            lines.append(line)
    result = "".join(lines)
    return re.sub(r"(`+)([^`]*?)\1", lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)), result)


class IntegrityCheck:
    def __init__(self, vault, site_id):
        self.vault = Path(vault).resolve()
        self.site_id = site_id
        self.site = self.vault / "sites" / site_id
        self.counts = Counter({name: 0 for name in (
            "graphNodes", "graphEdges", "internalPages", "graphNoteFilesChecked",
            "canvasNodes", "canvasEdges", "resources", "localResourceFilesChecked",
            "captionResources", "captionFilesChecked", "referenceOnlyResources",
            "transformedResourceFiles", "inventoryFilesChecked", "inventoryRawFilesChecked",
            "inventoryMediaFilesChecked", "markdownFilesScanned", "localImageEmbedsChecked",
            "fetchReceiptRows", "receiptRowsWithoutRetainedBytes", "rawReceiptFilesChecked")})
        self.failures = []
        self.unchecked = []
        self.evidence = {}
        self.hashes = {}
        self.embed_names = None

    def fail(self, check, **details):
        self.failures.append({"check": check, **details})

    def path(self, base, relative, check):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            self.fail(check, path=relative, reason="Expected a nonempty vault-relative POSIX path")
            return None
        part = Path(relative)
        if part.is_absolute() or ".." in part.parts:
            self.fail(check, path=relative, reason="Unsafe file path")
            return None
        candidate = base / part
        try:
            current = base
            symlink = False
            for segment in part.parts:
                current = current / segment
                symlink = symlink or current.is_symlink()
            if symlink or base.resolve() not in candidate.resolve().parents:
                self.fail(check, path=relative, reason="Symlink or path outside its capture boundary")
                return None
            if not candidate.is_file():
                self.fail(check, path=relative, reason="Referenced file is missing")
                return None
        except OSError as error:
            self.fail(check, path=relative, reason=str(error))
            return None
        return candidate

    def load_json(self, path, check, optional=False):
        if optional and not path.is_file():
            self.unchecked.append({"check": check, "reason": "File is absent", "file": str(path)})
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            self.fail(check, file=str(path), reason=str(error))
            return None

    def hash_file(self, path):
        key = str(path.resolve())
        if key not in self.hashes:
            self.hashes[key] = sha256(path)
        return self.hashes[key]

    def check_hash(self, path, expected, check, reference):
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            self.fail(check, path=reference, expected=expected, reason="Missing or invalid SHA-256")
            return False
        actual = self.hash_file(path)
        if expected.lower() != actual:
            self.fail(check, path=reference, expected=expected, actual=actual, reason="Stored bytes differ from recorded SHA-256")
            return False
        return True

    def graph(self, manifest):
        nodes, edges, stats = manifest.get("nodes"), manifest.get("edges"), manifest.get("stats")
        if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(stats, dict):
            self.fail("graph-schema", reason="Expected nodes, edges and stats")
            return [], []
        if any(not isinstance(node, dict) or not isinstance(node.get("id"), str) for node in nodes):
            self.fail("graph-schema", reason="Invalid graph node record")
            return [], []
        ids = {node["id"] for node in nodes}
        if len(ids) != len(nodes):
            self.fail("graph-node-ids", reason="Duplicate node IDs")
        internals = [node for node in nodes if node.get("kind") != "external-domain"]
        self.counts.update(graphNodes=len(nodes), graphEdges=len(edges), internalPages=len(internals))
        if type(stats.get("pagesCrawled")) is not int or stats["pagesCrawled"] != len(internals):
            self.fail("graph-page-count", recorded=stats.get("pagesCrawled"), actual=len(internals))
        for node in nodes:
            note = self.path(self.vault, node.get("obsidianPath"), "graph-note-file")
            if note:
                self.counts["graphNoteFilesChecked"] += 1
            if node in internals:
                relative = node.get("obsidianPath", "")
                if not relative.startswith(f"sites/{self.site_id}/pages/") or not relative.endswith(".md"):
                    self.fail("page-resource-separation", nodeId=node["id"], path=relative, reason="Internal page note lies outside pages/")
                suffix = Path(unquote(urlparse(str(node.get("url", ""))).path)).suffix.lower()
                if suffix in MEDIA_EXTENSIONS:
                    self.fail("page-resource-separation", nodeId=node["id"], url=node.get("url"), reason="Known media URL appears as an HTML page")
        seen = set()
        for edge in edges:
            if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
                self.fail("graph-edge-schema", reason="Invalid edge record")
                continue
            if edge["id"] in seen or edge.get("source") not in ids or edge.get("target") not in ids:
                self.fail("graph-edge-references", edgeId=edge["id"], reason="Duplicate ID or missing endpoint")
            seen.add(edge["id"])
        self.evidence["graph"] = {"capturedAt": manifest.get("capturedAt"), "captureStatus": manifest.get("captureStatus"), "stats": stats}
        return internals, edges

    def canvas(self, internals, edges):
        canvas = self.load_json(self.site / "_sitemap.canvas", "canvas-json")
        if not isinstance(canvas, dict) or not isinstance(canvas.get("nodes"), list) or not isinstance(canvas.get("edges"), list):
            self.fail("canvas-schema", reason="Expected Canvas nodes and edges")
            return
        expected_nodes = {node["id"] for node in internals}
        actual_nodes = [node.get("id") for node in canvas["nodes"] if isinstance(node, dict)]
        self.counts.update(canvasNodes=len(actual_nodes), canvasEdges=len(canvas["edges"]))
        if len(actual_nodes) != len(expected_nodes) or set(actual_nodes) != expected_nodes:
            self.fail("canvas-node-coverage", missing=sorted(expected_nodes - set(actual_nodes)), unexpected=sorted(set(actual_nodes) - expected_nodes, key=str))
        expected_edges = {edge["id"] for edge in edges if isinstance(edge, dict) and edge.get("kind") in ("sitemap-hierarchy", "internal-body") and edge.get("source") in expected_nodes and edge.get("target") in expected_nodes}
        actual_edges = [edge.get("id") for edge in canvas["edges"] if isinstance(edge, dict)]
        if len(actual_edges) != len(expected_edges) or set(actual_edges) != expected_edges:
            self.fail("canvas-edge-coverage", missing=sorted(expected_edges - set(actual_edges)), unexpected=sorted(set(actual_edges) - expected_edges, key=str))
        for edge in canvas["edges"]:
            if not isinstance(edge, dict) or edge.get("fromNode") not in expected_nodes or edge.get("toNode") not in expected_nodes:
                self.fail("canvas-edge-endpoints", edge=edge)
        notes = {node["id"]: node.get("obsidianPath") for node in internals}
        for node in canvas["nodes"]:
            if isinstance(node, dict) and (node.get("type") != "file" or node.get("file") != notes.get(node.get("id"))):
                self.fail("canvas-note-identity", nodeId=node.get("id"), path=node.get("file"))

    def resources(self, manifest, internals):
        resources = manifest.get("resources")
        if not isinstance(resources, list):
            self.fail("resource-schema", reason="Expected resource inventory")
            return
        internal_urls = {node.get("url") for node in internals}
        records = []
        for entry in resources:
            if not isinstance(entry, dict):
                self.fail("resource-schema", reason="Invalid resource record")
                continue
            if entry.get("url") in internal_urls:
                self.fail("page-resource-separation", resourceId=entry.get("id"), url=entry.get("url"), reason="URL is stored as both page and resource")
            if entry.get("type") == "transcript":
                self.counts["captionResources"] += 1
            relative = entry.get("localPath")
            if not relative:
                self.counts["referenceOnlyResources"] += 1
                if entry.get("downloadState") == "saved":
                    self.fail("resource-local-path", resourceId=entry.get("id"), reason="Saved resource has no localPath")
                continue
            path = self.path(self.vault, relative, "resource-local-file")
            if not path:
                continue
            self.counts["localResourceFilesChecked"] += 1
            if not relative.startswith(f"sites/{self.site_id}/assets/"):
                self.fail("page-resource-separation", path=relative, reason="Resource file is outside assets/")
            size = path.stat().st_size
            if type(entry.get("bytes")) is not int or entry["bytes"] != size:
                self.fail("resource-byte-count", path=relative, expected=entry.get("bytes"), actual=size)
            valid = self.check_hash(path, entry.get("sha256"), "resource-file-hash", relative)
            if entry.get("type") == "transcript" or path.suffix.lower() in CAPTION_EXTENSIONS:
                self.counts["captionFilesChecked"] += 1
            if entry.get("sourceSha256") and entry.get("sourceSha256") != entry.get("sha256"):
                self.counts["transformedResourceFiles"] += 1
            records.append({"id": entry.get("id"), "type": entry.get("type"), "path": relative,
                            "bytes": size, "sha256": self.hash_file(path), "verified": valid,
                            "sourceSha256": entry.get("sourceSha256")})
        self.counts["resources"] = len(resources)
        self.evidence["resourceFiles"] = records
        self.evidence["resourceTypeCounts"] = dict(Counter(entry.get("type", "unknown") for entry in resources if isinstance(entry, dict)))

    def generated_inventory(self):
        inventory = self.load_json(self.site / "_generated-files.json", "generated-inventory-json")
        if not isinstance(inventory, dict) or not isinstance(inventory.get("files"), dict):
            self.fail("generated-inventory-schema", reason="Expected generated file records")
            return
        verified = {}
        for relative, record in inventory["files"].items():
            path = self.path(self.site, relative, "inventory-file")
            if not path:
                continue
            self.counts["inventoryFilesChecked"] += 1
            if not isinstance(record, dict):
                self.fail("inventory-installed-hash", path=relative, reason="Inventory record has no installedSha256 semantics")
                continue
            self.check_hash(path, record.get("installedSha256"), "inventory-installed-hash", relative)
            verified[relative] = self.hash_file(path)
            if relative.startswith("_raw/"):
                self.counts["inventoryRawFilesChecked"] += 1
            if relative.startswith("assets/"):
                self.counts["inventoryMediaFilesChecked"] += 1
        self.evidence["inventoryFileHashes"] = verified

    def resolve_embed(self, note, target):
        candidates = [self.vault / target, note.parent / target, self.site / target, self.site / "assets" / target]
        if "/" not in target:
            if self.embed_names is None:
                self.embed_names = {}
                for file in self.site.rglob("*"):
                    if file.is_file() and not file.is_symlink():
                        self.embed_names.setdefault(file.name, []).append(file)
            candidates.extend(self.embed_names.get(target, []))
        for path in candidates:
            try:
                if path.is_file() and not path.is_symlink() and self.vault in path.resolve().parents:
                    return path
            except OSError:
                pass
        return None

    def notes_and_embeds(self):
        targets = set()
        for note in sorted(self.site.rglob("*.md")):
            if note.is_symlink():
                self.fail("note-symlink", path=str(note))
                continue
            try:
                text = markdown_without_code(note.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as error:
                self.fail("note-text", path=str(note), reason=str(error))
                continue
            self.counts["markdownFilesScanned"] += 1
            for match in re.finditer(r"(?<!\\)(?P<embed>!)?\[\[(?P<body>[^\]]*?)\]\]", text, re.S):
                body = match.group("body")
                line = text[:match.start()].count("\n") + 1
                if "\n" in body:
                    self.fail("multiline-wikilink", path=note.relative_to(self.vault).as_posix(), line=line, value=body[:180])
                target = body.split("|", 1)[0].split("#", 1)[0].strip()
                if not match.group("embed") or Path(target).suffix.lower() not in IMAGE_EXTENSIONS or urlparse(target).scheme:
                    continue
                self.counts["localImageEmbedsChecked"] += 1
                resolved = self.resolve_embed(note, target)
                if resolved is None:
                    self.fail("local-image-embed", path=note.relative_to(self.vault).as_posix(), line=line, target=target)
                else:
                    targets.add(resolved.relative_to(self.vault).as_posix())
        self.evidence["resolvedImageEmbedFiles"] = sorted(targets)

    def raw_receipts(self):
        log = self.load_json(self.site / "_fetch-log.json", "fetch-log-json", optional=True)
        if not isinstance(log, dict) or not isinstance(log.get("entries"), list):
            self.unchecked.append({"check": "fetch-log-byte-hashes", "reason": "Unknown fetch-log schema; generated inventory hashes remain independently checked"})
            return
        records = []
        for row in log["entries"]:
            if not isinstance(row, dict):
                self.unchecked.append({"check": "fetch-log-row", "reason": "Unknown row format"})
                continue
            self.counts["fetchReceiptRows"] += 1
            if "rawPath" not in row and "rawArtifact" not in row:
                self.unchecked.append({"check": "fetch-log-row-byte-hashes", "reason": "Row has no recognized raw artifact path field", "url": row.get("url")})
                continue
            if "rawPath" not in row and row.get("rawArtifact"):
                row = {**row, "rawPath": row["rawArtifact"]}
            if not row.get("rawPath"):
                self.counts["receiptRowsWithoutRetainedBytes"] += 1
                if row.get("textPath"):
                    self.fail("receipt-source-identity", path=row["textPath"], reason="Decoded text sidecar has no original body artifact")
                continue
            for path_key, hash_key in (("rawPath", "rawSha256"), ("textPath", "textSha256")):
                relative = row.get(path_key)
                if not relative:
                    continue
                path = self.path(self.site, relative, "receipt-file")
                if not path:
                    continue
                self.counts["rawReceiptFilesChecked"] += 1
                if not relative.startswith("_raw/"):
                    self.fail("page-resource-separation", path=relative, reason="Page receipt bytes are stored outside _raw/")
                valid = self.check_hash(path, row.get(hash_key), "receipt-file-hash", relative)
                with path.open("rb") as stream:
                    signature = media_signature(stream.read(1024))
                if signature:
                    self.fail("page-resource-separation", path=relative, reason="Page raw artifact contains known media bytes", signature=signature)
                records.append({"path": relative, "rawKind": row.get("rawKind"), "sha256": self.hash_file(path), "verified": valid})
        self.evidence["rawReceiptFiles"] = records

    def run(self):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,179}", self.site_id):
            self.fail("site-id", reason="Unsafe site ID")
            return self.report()
        if (self.vault / "sites").is_symlink() or self.site.is_symlink() or self.vault not in self.site.resolve().parents or not self.site.is_dir():
            self.fail("site-folder", reason="Missing capture folder or symlink")
            return self.report()
        manifest = self.load_json(self.site / "_site-graph.json", "graph-json")
        if not isinstance(manifest, dict):
            return self.report()
        if manifest.get("siteId") != self.site_id:
            self.fail("site-identity", recorded=manifest.get("siteId"), requested=self.site_id)
        internals, edges = self.graph(manifest)
        self.canvas(internals, edges)
        self.resources(manifest, internals)
        self.generated_inventory()
        self.notes_and_embeds()
        self.raw_receipts()
        return self.report()

    def report(self):
        return {"schemaVersion": 1, "checkedAt": datetime.now(timezone.utc).isoformat(),
                "readOnly": True, "networkUsed": False, "vault": str(self.vault), "siteId": self.site_id,
                "status": "FAIL" if self.failures else "PARTIAL" if self.unchecked else "PASS",
                "counts": dict(sorted(self.counts.items())), "failures": self.failures,
                "unchecked": self.unchecked, "evidence": self.evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--evidence", required=True, help="Output JSON outside the inspected vault")
    options = parser.parse_args()
    vault, output = Path(options.vault).resolve(), Path(options.evidence).resolve()
    if output == vault or vault in output.parents:
        parser.error("Evidence output must be outside the inspected vault to preserve read-only behavior.")
    checker = IntegrityCheck(vault, options.site)
    try:
        report = checker.run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        checker.fail("validation-interrupted", reason=type(error).__name__ + ": " + str(error))
        report = checker.report()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": report["counts"],
                      "failures": len(report["failures"]), "unchecked": len(report["unchecked"]),
                      "evidence": str(output)}, ensure_ascii=False))
    return 1 if report["status"] == "FAIL" else 2 if report["status"] == "PARTIAL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
