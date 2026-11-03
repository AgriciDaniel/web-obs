#!/usr/bin/env python3
"""Canvas inventory regressions using synthetic graph data and no network."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from crawl_site import generate_sitemap_canvas


def page(number, depth=1):
    return {"id": f"page-{number}", "kind": "home" if number == 0 else "page",
            "health": "home" if number == 0 else "healthy", "clickDepth": depth,
            "section": "root" if number == 0 else "articles",
            "url": f"https://fixture.example/page-{number}",
            "obsidianPath": f"sites/fixture.example/pages/page-{number}.md"}


def edge(number, source, target, kind="internal-body"):
    return {"id": f"edge-{number}", "source": source, "target": target, "kind": kind}


class CanvasExportTests(unittest.TestCase):
    def test_wide_depth_retains_every_page_and_connection(self):
        nodes = [page(0, 0)] + [page(number) for number in range(1, 41)]
        edges = [edge(number, "page-0", f"page-{number}") for number in range(1, 41)]
        canvas = generate_sitemap_canvas(nodes, edges)
        self.assertEqual({node["id"] for node in canvas["nodes"]}, {node["id"] for node in nodes})
        self.assertEqual({item["id"] for item in canvas["edges"]}, {item["id"] for item in edges})
        self.assertEqual(len(canvas["nodes"]), 41)
        self.assertEqual(len(canvas["edges"]), 40)
        positions = {(node["x"], node["y"]) for node in canvas["nodes"]}
        self.assertEqual(len(positions), len(nodes))

    def test_250_page_export_has_complete_inventory_and_valid_endpoints(self):
        nodes = [page(number, number % 10) for number in range(250)]
        edges = [edge(number, f"page-{number - 1}", f"page-{number}",
                      "sitemap-hierarchy" if number % 2 else "internal-body")
                 for number in range(1, 250)]
        canvas = json.loads(json.dumps(generate_sitemap_canvas(nodes, edges)))
        exported_ids = {node["id"] for node in canvas["nodes"]}
        self.assertEqual(len(canvas["nodes"]), 250)
        self.assertEqual(exported_ids, {node["id"] for node in nodes})
        self.assertEqual(len(canvas["edges"]), 249)
        self.assertEqual({item["id"] for item in canvas["edges"]}, {item["id"] for item in edges})
        for item in canvas["edges"]:
            self.assertIn(item["fromNode"], exported_ids)
            self.assertIn(item["toNode"], exported_ids)
        self.assertEqual(len({(node["x"], node["y"]) for node in canvas["nodes"]}), 250)
        for node in canvas["nodes"]:
            self.assertEqual(node["type"], "file")
            self.assertTrue(node["file"].endswith(".md"))
            self.assertGreater(node["width"], 0)
            self.assertGreater(node["height"], 0)

    def test_distinct_eligible_relationships_with_same_endpoints_are_retained(self):
        nodes = [page(0, 0), page(1)]
        edges = [edge(1, "page-0", "page-1", "sitemap-hierarchy"),
                 edge(2, "page-0", "page-1", "internal-body")]
        canvas = generate_sitemap_canvas(nodes, edges)
        self.assertEqual([item["id"] for item in canvas["edges"]], ["edge-1", "edge-2"])

    def test_external_and_unknown_endpoints_do_not_create_dangling_edges(self):
        nodes = [page(0, 0), page(1), {**page(9), "kind": "external-domain"}]
        edges = [edge(1, "page-0", "page-1"), edge(2, "page-0", "page-9"),
                 edge(3, "page-0", "missing"), edge(4, "missing", "page-1"),
                 edge(5, "page-0", "page-1", "external"),
                 edge(6, "page-0", "page-1", "internal-chrome")]
        canvas = generate_sitemap_canvas(nodes, edges)
        self.assertEqual({node["id"] for node in canvas["nodes"]}, {"page-0", "page-1"})
        self.assertEqual([item["id"] for item in canvas["edges"]], ["edge-1"])

    def test_unreachable_pages_remain_in_canvas(self):
        nodes = [page(0, 0), {**page(1), "clickDepth": None, "health": "orphan"}]
        canvas = generate_sitemap_canvas(nodes, [])
        self.assertEqual({node["id"] for node in canvas["nodes"]}, {"page-0", "page-1"})
        self.assertEqual(canvas["edges"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
