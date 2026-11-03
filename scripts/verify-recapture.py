#!/usr/bin/env python3
"""Recapture safety tests use only a local website and temporary vaults."""
from contextlib import redirect_stdout, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import crawl_site


class Website(BaseHTTPRequestHandler):
    version = 1
    extra_resource = False
    def log_message(self, *_args):
        pass
    def do_GET(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if self.path == '/robots.txt':
            content = f'User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml'
            kind = 'text/plain'
        elif self.path == '/sitemap.xml':
            content = f'<urlset><url><loc>{origin}/</loc></url><url><loc>{origin}/second</loc></url></urlset>'
            kind = 'application/xml'
        elif self.path == '/legacy.vtt':
            content, kind = 'WEBVTT\n\n00:00.000 --> 00:01.000\nRetained caption.\n', 'text/vtt'
        elif self.path in ('/', '/second'):
            content = f'<html><head><title>Page {self.version}</title></head><body><h1>Version {self.version}</h1><p>Original website text.</p><a href="/second">Second</a></body></html>'
            if self.extra_resource:
                content = content.replace('</body>', '<a href="/legacy.vtt">Caption</a></body>')
            kind = 'text/html'
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.end_headers()
        self.wfile.write(content.encode())


class RecaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Website)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.allow = patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS': f'127.0.0.1:{cls.server.server_port}'})
        cls.allow.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)
        cls.allow.stop()

    def capture(self, root, **kwargs):
        with redirect_stdout(io.StringIO()):
            return crawl_site.crawl_website_to_vault(self.origin, root, render_mode='never', delay_sec=0, download_images=False, **kwargs)

    def test_member_annotations_survive_a_recapture(self):
        with tempfile.TemporaryDirectory() as directory:
            Website.version = 1
            first = self.capture(directory)
            home = next(node for node in first['nodes'] if node['kind'] == 'home')
            note = Path(directory) / home['obsidianPath']
            note.write_text(note.read_text() + '\n## My notes\nKeep this annotation.\n')
            manual = note.parent / 'my-research.md'
            manual.write_text('A manually created note.\n')
            Website.version = 2
            second = self.capture(directory)
            self.assertIn('Keep this annotation.', note.read_text())
            self.assertEqual(manual.read_text(), 'A manually created note.\n')
            current_home = next(node for node in second['nodes'] if node['kind'] == 'home')
            self.assertEqual(current_home['noteStatus'], 'preserved-local-edits')
            proposal = Path(directory) / current_home['proposedNotePath']
            self.assertIn('Version 2', proposal.read_text())
            self.assertEqual(second['preservationStatus'], 'conflicts')
            self.assertTrue(list((Path(directory) / '.web-obs/history').rglob('_site-graph.json')))

    def test_failure_leaves_previous_capture_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.capture(directory)
            site = Path(directory) / 'sites' / first['siteId']
            before = {str(p.relative_to(site)): p.read_bytes() for p in site.rglob('*') if p.is_file()}
            with patch.object(crawl_site, 'extract_page_data', side_effect=RuntimeError('Fixture failed')):
                with self.assertRaisesRegex(RuntimeError, 'Fixture failed'):
                    self.capture(directory)
            after = {str(p.relative_to(site)): p.read_bytes() for p in site.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_unedited_generated_notes_update(self):
        with tempfile.TemporaryDirectory() as directory:
            Website.version = 1
            first = self.capture(directory)
            Website.version = 2
            second = self.capture(directory)
            home = next(node for node in second['nodes'] if node['kind'] == 'home')
            self.assertIn('Version 2', (Path(directory) / home['obsidianPath']).read_text())
            self.assertNotIn('noteStatus', home)
            self.assertEqual(first['siteId'], second['siteId'])

    def test_preserved_asset_hashes_match_installed_member_bytes_and_keep_fresh_proposal(self):
        from capture_store import CaptureTransaction, write_json
        site_id = 'asset-fixture.example'
        relative_asset = 'assets/chart.svg'
        original = b'<svg>Original generated asset</svg>'
        fresh = b'<svg>Fresh generated asset</svg>'
        member = b'<svg>Member edited asset retained locally</svg>'

        def install(directory, raw):
            with CaptureTransaction(directory) as transaction:
                staged = transaction.stage / 'sites' / site_id
                (staged / 'assets').mkdir(parents=True)
                (staged / 'pages').mkdir()
                (staged / relative_asset).write_bytes(raw)
                (staged / 'pages/index.md').write_text('# Fixture\n')
                digest = hashlib.sha256(raw).hexdigest()
                resource = {'id': 'resource-chart', 'url': 'https://asset-fixture.example/chart.svg',
                            'type': 'image', 'localPath': f'sites/{site_id}/{relative_asset}',
                            'bytes': len(raw), 'sha256': digest, 'sourceBytes': len(raw),
                            'sourceSha256': digest, 'downloadState': 'saved', 'references': []}
                manifest = {'siteId': site_id, 'captureStatus': 'complete', 'captureWarnings': [],
                            'nodes': [{'id': 'home', 'obsidianPath': f'sites/{site_id}/pages/index.md'}],
                            'edges': [], 'resources': [resource]}
                write_json(staged / '_site-graph.json', manifest)
                write_json(staged / '_site-summary.json', {'resources': [resource]})
                write_json(staged / '_resources.json', {'resources': [resource]})
                return transaction.commit(manifest)

        for edited_asset, edited_report in ((False, False), (True, False), (True, True)):
            with self.subTest(edited_asset=edited_asset, edited_report=edited_report), tempfile.TemporaryDirectory() as directory:
                install(directory, original)
                site = Path(directory) / 'sites' / site_id
                if edited_asset:
                    (site / relative_asset).write_bytes(member)
                member_report = None
                if edited_report:
                    data = json.loads((site / '_resources.json').read_text())
                    data['memberNote'] = 'Keep the edited resource report byte for byte.'
                    member_report = (json.dumps(data) + '\n').encode()
                    (site / '_resources.json').write_bytes(member_report)
                manifest = install(directory, fresh)
                row = manifest['resources'][0]
                actual = (site / relative_asset).read_bytes()
                self.assertEqual(actual, member if edited_asset else fresh)
                self.assertEqual((row['sha256'], row['bytes']), (hashlib.sha256(actual).hexdigest(), len(actual)))
                self.assertEqual((row['sourceSha256'], row['sourceBytes']), (hashlib.sha256(fresh).hexdigest(), len(fresh)))
                graph = json.loads((site / '_site-graph.json').read_text())
                summary = json.loads((site / '_site-summary.json').read_text())
                self.assertEqual(graph['resources'], manifest['resources'])
                self.assertEqual(summary['resources'], manifest['resources'])
                baseline = json.loads((site / '_generated-files.json').read_text())['files']
                self.assertEqual(baseline[relative_asset]['generatedSha256'], hashlib.sha256(fresh).hexdigest())
                self.assertEqual(baseline[relative_asset]['installedSha256'], hashlib.sha256(actual).hexdigest())
                if edited_asset:
                    self.assertEqual(row['localFileStatus'], 'preserved-local-edits')
                    self.assertEqual((Path(directory) / row['proposedLocalPath']).read_bytes(), fresh)
                else:
                    self.assertNotIn('localFileStatus', row)
                    self.assertNotIn('proposedLocalPath', row)
                if edited_report:
                    self.assertEqual((site / '_resources.json').read_bytes(), member_report)
                    self.assertTrue(any(item['path'] == '_resources.json' for item in manifest['recapture']['preservedFiles']))
                else:
                    self.assertEqual(json.loads((site / '_resources.json').read_text())['resources'], manifest['resources'])
                    self.assertEqual(baseline['_resources.json']['generatedSha256'],
                                     hashlib.sha256((site / '_resources.json').read_bytes()).hexdigest())

    def test_reclassified_media_note_is_archived_and_member_edit_is_retained(self):
        for edited in (False, True):
            with self.subTest(edited=edited), tempfile.TemporaryDirectory() as directory:
                first = self.capture(directory)
                site = Path(directory) / 'sites' / first['siteId']
                legacy = site / 'pages/legacy-audio.md'
                legacy.write_text('Legacy generated transcript page.\n')
                inventory_path = site / '_generated-files.json'
                inventory = json.loads(inventory_path.read_text())
                inventory['files']['pages/legacy-audio.md'] = {'generatedSha256': hashlib.sha256(legacy.read_bytes()).hexdigest()}
                inventory_path.write_text(json.dumps(inventory))
                graph_path = site / '_site-graph.json'
                graph = json.loads(graph_path.read_text())
                graph['nodes'].append({**graph['nodes'][0], 'id': 'legacy-resource', 'kind': 'page', 'url': self.origin + '/legacy.vtt', 'obsidianPath': f"sites/{first['siteId']}/pages/legacy-audio.md"})
                graph_path.write_text(json.dumps(graph))
                if edited:
                    legacy.write_text(legacy.read_text() + 'Keep this member annotation.\n')
                Website.extra_resource = True
                try:
                    second = self.capture(directory, max_pages=1, check_external=False)
                finally:
                    Website.extra_resource = False
                self.assertEqual(second['captureStatus'], 'partial')
                self.assertFalse(any(n['url'].endswith('.vtt') for n in second['nodes']))
                self.assertTrue(any(r['type'] == 'transcript' for r in second['resources']))
                self.assertEqual(legacy.exists(), edited)
                if edited:
                    self.assertIn('Keep this member annotation.', legacy.read_text())
                history = Path(directory) / '.web-obs/history'
                self.assertTrue(list(history.rglob('legacy-audio.md')))

    def test_vault_lock_excludes_concurrent_capture(self):
        from capture_store import CaptureTransaction
        with tempfile.TemporaryDirectory() as directory:
            with CaptureTransaction(directory):
                with self.assertRaisesRegex(RuntimeError, 'Another capture'):
                    with CaptureTransaction(directory):
                        pass

    def test_symlink_destination_is_refused(self):
        from capture_store import CaptureTransaction
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            (Path(directory) / 'sites').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                with CaptureTransaction(directory):
                    pass

    def test_predictable_temporary_symlink_does_not_overwrite_member_file(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            control = Path(directory) / '.web-obs'
            control.mkdir()
            member = Path(outside) / 'member.md'
            member.write_text('Private member text.')
            (control / 'promotion.json.tmp').symlink_to(member)
            self.capture(directory)
            self.assertEqual(member.read_text(), 'Private member text.')

    def test_recovery_restores_interrupted_previous_capture(self):
        from capture_store import CaptureTransaction, write_json
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            active = Path(directory) / 'sites' / manifest['siteId']
            history = Path(directory) / '.web-obs/history' / manifest['siteId'] / 'interrupted'
            history.parent.mkdir(parents=True, exist_ok=True)
            os.replace(active, history)
            write_json(Path(directory) / '.web-obs/promotion.json', {'siteId': manifest['siteId'], 'historyId': 'interrupted'})
            with CaptureTransaction(directory):
                self.assertTrue((active / '_site-graph.json').is_file())
                self.assertFalse(history.exists())

    def test_failed_promotion_rolls_back_previous_capture(self):
        import capture_store
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            active = Path(directory) / 'sites' / manifest['siteId']
            before = (active / '_site-graph.json').read_bytes()
            original = os.replace
            def fail_promotion(source, destination):
                if '/staging/' in str(source) and Path(destination) == active:
                    raise RuntimeError('Promotion failed fixture')
                return original(source, destination)
            with patch.object(capture_store.os, 'replace', fail_promotion):
                with self.assertRaisesRegex(RuntimeError, 'Promotion failed'):
                    self.capture(directory)
            self.assertEqual((active / '_site-graph.json').read_bytes(), before)

    def test_edit_at_publication_boundary_aborts_without_losing_it(self):
        import capture_store
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            note = Path(directory) / 'sites' / manifest['siteId'] / 'pages/index.md'
            @contextmanager
            def edit_before_swap():
                note.write_text(note.read_text() + '\nLate member edit.\n')
                yield
            with patch.object(capture_store, 'promotion_signals', edit_before_swap):
                with self.assertRaisesRegex(RuntimeError, 'changed during publication'):
                    self.capture(directory)
            self.assertIn('Late member edit.', note.read_text())

    def test_edit_after_history_rename_is_rolled_back_and_preserved(self):
        import capture_store
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            active = Path(directory) / 'sites' / manifest['siteId']
            original = os.replace
            def edit_after_rename(source, destination):
                result = original(source, destination)
                if Path(source) == active and '/history/' in str(destination):
                    note = Path(destination) / 'pages/index.md'
                    note.write_text(note.read_text() + '\nEdit during promotion.\n')
                return result
            with patch.object(capture_store.os, 'replace', edit_after_rename):
                with self.assertRaisesRegex(RuntimeError, 'changed during publication'):
                    self.capture(directory)
            self.assertIn('Edit during promotion.', (active / 'pages/index.md').read_text())

    def test_oversized_graph_is_refused_before_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.capture(directory)
            active = Path(directory) / 'sites' / manifest['siteId'] / '_site-graph.json'
            previous = active.read_bytes()
            original = crawl_site._capture_to_staging
            def oversized(*args, **kwargs):
                result = original(*args, **kwargs)
                result['nodes'] = result['nodes'] * 20001
                return result
            with patch.object(crawl_site, '_capture_to_staging', oversized):
                with self.assertRaisesRegex(ValueError, 'inventory budget'):
                    self.capture(directory)
            self.assertEqual(active.read_bytes(), previous)


if __name__ == '__main__':
    unittest.main(verbosity=2)
