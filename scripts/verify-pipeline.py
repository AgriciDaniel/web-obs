#!/usr/bin/env python3
"""Local fixture integration checks and optional serial/parallel capture benchmark."""
import argparse
import base64
from collections import Counter
from concurrent.futures import Future
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from extractor import extract_page_data
import pipeline
from pipeline import collect_site
from pipeline_serial import SerialDispatcher
from site_intel import build_robots_policy
from workers import origin_key

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
CAPTIONS = b'WEBVTT\n\n00:00.000 --> 00:01.000\nA retained caption.\n'
SVG = (b'<svg xmlns="http://www.w3.org/2000/svg">\n<script>unsafe()</script>'
       b'<rect width="4" height="4" onload="unsafe()"/></svg>')
BENCHMARK = False
BENCHMARK_OUTPUT = None


class Website(BaseHTTPRequestHandler):
    mode = 'media'
    lock = threading.Lock()
    hits = []
    active = 0
    peak = 0

    def log_message(self, *_args):
        pass

    @classmethod
    def reset(cls, mode='media'):
        with cls.lock:
            cls.mode, cls.hits, cls.active, cls.peak = mode, [], 0, 0

    def do_HEAD(self):
        self.respond(False)

    def do_GET(self):
        self.respond(True)

    def respond(self, include_body):
        started = time.monotonic()
        work_released = False
        with self.lock:
            self.hits.append((self.command, self.path, started))
            type(self).active += 1
            type(self).peak = max(type(self).peak, type(self).active)

        def release_work():
            nonlocal work_released
            if not work_released:
                with self.lock:
                    type(self).active -= 1
                work_released = True

        try:
            origin = f'http://127.0.0.1:{self.server.server_port}'
            external = f'http://localhost:{self.server.server_port}'
            kind, status, delay = 'text/html', 200, 0
            if self.path == '/robots.txt':
                kind, body = 'text/plain', f'User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml'.encode()
            elif self.path == '/sitemap.xml':
                paths = ['/', '/audio', '/watch', '/caption.vtt', '/voice.m4a', '/clip.mp4', '/live.mpd', '/extensionless-audio']
                if self.mode == 'budget-clean':
                    paths = ['/']
                body = ('<urlset>' + ''.join(f'<url><loc>{origin}{path}</loc></url>' for path in paths) + '</urlset>').encode()
                kind = 'application/xml'
            elif self.path == '/':
                extras = ''.join(f'<a href="/slow-{i}">Article {i}</a>' for i in range(12)) if self.mode == 'benchmark' else '<a href="/article">Article</a>'
                body = (f'<html><head><title>Fixture library</title></head><body><h1>Fixture library</h1>'
                        '<a href="/audio">Audio landing page</a><a href="/watch">Video landing page</a>'
                        '<a href="/extensionless-audio">Stream</a><a href="/caption.vtt">Transcript</a>'
                        '<a href="/voice.m4a">Audio file</a><a href="/clip.mp4">Video file</a>'
                        '<a href="/live.mpd">Video manifest</a><a href="/missing">Missing page</a>'
                        '<a href="/unavailable">Unavailable page</a><a href="/disconnect">Disconnected page</a>'
                        '<audio src="/voice.m4a" aria-label="Interview"></audio>'
                        '<video poster="/poster.png"><source src="/clip.mp4" type="video/mp4">'
                        '<track kind="captions" src="/caption.vtt" srclang="en" label="English"></video>'
                        '<img src="/poster.png" alt="Tour poster"><img src="/mislabelled-image.png" alt="Mislabeled image">'
                        f'<a href="{external}/external-ok">External reference</a>'
                        f'{extras}</body></html>').encode()
                if self.mode == 'samples':
                    body += b'<p>HomeMarker</p>'
                    delay = .6
                if self.mode.startswith('variants'):
                    body += (b'<picture><source srcset="/variant-small.png 1x, /variant-large.png 2x">'
                             b'<img src="/primary.png" alt="Primary image"></picture>'
                             b'<link rel="icon" href="/icon.png">')
                if self.mode == 'budget-clean':
                    body = (b'<html><title>Clean image fixture</title><h1>Clean image fixture</h1>'
                            b'<img src="/primary.png" alt="First"><img src="/variant-small.png" alt="Second">'
                            b'<img src="/variant-large.png" alt="Third"></html>')
                if self.mode == 'svg':
                    body += b'<img src="/chart.svg" alt="Sanitized chart">'
            elif self.path in ('/audio', '/watch', '/article') or self.path.startswith(('/slow-', '/sample-')):
                body = f'<html><title>{self.path} title</title><h1>{self.path} landing page</h1><p>Local source text.</p></html>'.encode()
                if self.path == '/article':
                    body += b'<a href="/extensionless-audio">Listen to the article audio</a>'
                    if self.mode == 'variants-late':
                        body += b'<img src="/variant-small.png" alt="Later primary image">'
                delay = .3 if self.path == '/article' else .25 if self.path.startswith('/slow-') else .08
            elif self.path == '/poster.png':
                kind, body, delay = 'image/png', PNG, .15
            elif self.path in ('/primary.png', '/variant-small.png', '/variant-large.png', '/icon.png'):
                kind, body = 'image/png', PNG
            elif self.path == '/chart.svg':
                kind, body = 'image/svg+xml', SVG
            elif self.path == '/caption.vtt':
                kind, body, delay = 'text/vtt', CAPTIONS, .08
            elif self.path in ('/voice.m4a', '/extensionless-audio'):
                kind, body = 'audio/mp4', b'Audio should remain a reference by default.'
            elif self.path == '/mislabelled-image.png':
                kind, body = 'audio/mp4', b'An image-shaped URL must not cause audio body downloads.'
            elif self.path == '/clip.mp4':
                kind, body = 'video/mp4', b'Video should remain a reference by default.'
            elif self.path == '/live.mpd':
                kind, body = 'application/dash+xml', b'<MPD />'
            elif self.path == '/external-ok':
                body = b'<html><h1>Checked reference</h1></html>'
            elif self.path == '/unavailable':
                status, body = 503, b'<html><h1>Temporarily unavailable</h1></html>'
            elif self.path == '/disconnect':
                release_work()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            else:
                status, body = 404, b'<html><h1>Not found</h1></html>'
            if kind == 'text/html' and status == 200:
                body += f'<!-- FixtureURL:{self.path} -->'.encode()
            if delay:
                time.sleep(delay)
            # Count application work before any response becomes visible. After
            # the response is readable, a serial client can legitimately start
            # its next request before this handler reaches its finally block.
            release_work()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if include_body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            release_work()


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Website)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'
        cls.env = patch.dict(os.environ, {'WEB_OBS_LOCAL_TARGETS':
                             f'127.0.0.1:{cls.server.server_port},localhost:{cls.server.server_port}'})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def collect(self, parallel, *, check_external=True, mode='media', max_pages=40,
                image_mode='preferred', download_images=True):
        Website.reset(mode)
        policy = build_robots_policy('User-agent: *\nAllow: /', 200)
        policies = {origin_key(self.origin): policy}
        paths = ['/', '/audio', '/watch', '/caption.vtt', '/voice.m4a', '/clip.mp4', '/live.mpd', '/extensionless-audio']
        if mode == 'samples':
            paths += [f'/sample-{number:02d}' for number in range(10)]
        sitemap = {self.origin + path: {} for path in paths}
        events, extracted_urls = [], []
        def extract(html, url, host, headers):
            extracted_urls.append(url)
            return extract_page_data(html, url, host, headers)
        with tempfile.TemporaryDirectory() as folder:
            result = collect_site(self.origin, self.origin, '127.0.0.1', sitemap,
                folder, 'fixture.test', max_pages, download_images, 'never', 0,
                policies, lambda url: policies.get(origin_key(url), policy),
                lambda url: urlparse(url).hostname in ('127.0.0.1', 'localhost'),
                lambda event, **data: events.append(json.loads(json.dumps({'event': event, **data}))),
                parallel=parallel, check_external=check_external, image_mode=image_mode, extract_fn=extract)
            retained = sorted(str(path.relative_to(folder)) for path in Path(folder).rglob('*') if path.is_file())
            artifacts = {str(path.relative_to(folder)): path.read_bytes() for path in Path(folder).rglob('*') if path.is_file()}
        return result, events, list(Website.hits), Website.peak, extracted_urls, retained, artifacts

    def test_media_are_associated_resources_and_html_audio_is_a_page(self):
        result, events, hits, peak, extracted, retained, artifacts = self.collect(True)
        pages = result['pages']
        self.assertIn(self.origin + '/audio', pages)
        self.assertIn(self.origin + '/watch', pages)
        inventory = {item['url']: item for item in result['resources']}
        for path in ['/caption.vtt', '/voice.m4a', '/clip.mp4', '/live.mpd', '/extensionless-audio']:
            self.assertNotIn(self.origin + path, pages)
            self.assertNotIn(self.origin + path, extracted)
            self.assertIn(self.origin + path, inventory)
        self.assertEqual(inventory[self.origin + '/extensionless-audio']['type'], 'audio')
        mislabeled = inventory[self.origin + '/mislabelled-image.png']
        self.assertEqual((mislabeled['type'], mislabeled['downloadState'], mislabeled['localPath'], mislabeled['bytes']),
                         ('audio', 'reference', None, 0))
        caption = inventory[self.origin + '/caption.vtt']
        self.assertEqual(caption['downloadState'], 'saved')
        self.assertTrue(any(ref['role'] == 'captions' and ref['language'] == 'en' for ref in caption['references']))
        self.assertIn(CAPTIONS, artifacts.values())
        methods = Counter((method, path) for method, path, _when in hits)
        self.assertEqual(methods['GET', '/poster.png'], 1)
        self.assertEqual(methods['HEAD', '/poster.png'], 0, 'Asset GET must supply the link result')
        self.assertEqual(methods['GET', '/caption.vtt'], 1)
        self.assertEqual(methods['HEAD', '/caption.vtt'], 0)
        for path in ['/voice.m4a', '/clip.mp4', '/live.mpd']:
            self.assertEqual(methods['GET', path], 0, 'Large media must not be downloaded by default')
            self.assertIsNone(inventory[self.origin + path]['localPath'])
        lanes = [event for event in events if event['event'] == 'pipeline_progress']
        self.assertTrue(lanes)
        self.assertTrue(all({'pages', 'media', 'links'} <= event.keys() for event in lanes))
        for event in lanes:
            links = event['links']
            self.assertEqual(links['discovered'], sum(links[key] for key in ('completed', 'failed', 'skipped', 'active', 'queued')), 'Reused asset results must leave the pending link count')
        self.assertTrue(any(event['pages']['active'] and event['media']['active'] for event in lanes),
                        'Page and media lanes should make overlapping progress')
        self.assertGreaterEqual(peak, 2)

    def test_check_external_false_keeps_references_without_destination_checks(self):
        result, _events, hits, *_rest = self.collect(True, check_external=False)
        self.assertTrue(result['resources'])
        self.assertFalse(any(path == '/external-ok' for _method, path, _when in hits))
        self.assertFalse(any(method == 'HEAD' for method, _path, _when in hits))
        self.assertTrue(any(row['method'] == 'GET' for row in result['link_results']))

    def test_saved_svg_hash_describes_sanitized_file_and_keeps_source_hash(self):
        result, events, _hits, _peak, _extracted, _retained, artifacts = self.collect(True, mode='svg')
        inventory = {row['url']: row for row in result['resources']}
        self.assertIn(self.origin + '/chart.svg', inventory, 'inventory=' + repr(sorted(inventory))[:600] + ' hits=' + repr([(m, p) for m, p, _w in _hits])[:600] + ' warnings=' + repr(result.get('warnings'))[:600] + ' events=' + repr([e for e in events if e.get('event') in ('error', 'warning')])[:600])
        svg = inventory[self.origin + '/chart.svg']
        stored = artifacts[svg['localPath'].removeprefix('sites/fixture.test/')]
        self.assertNotEqual(stored, SVG)
        self.assertNotIn(b'<script', stored)
        self.assertNotIn(b'onload', stored)
        self.assertEqual((svg['sourceBytes'], svg['sourceSha256']),
                         (len(SVG), hashlib.sha256(SVG).hexdigest()))
        self.assertEqual((svg['bytes'], svg['sha256']),
                         (len(stored), hashlib.sha256(stored).hexdigest()))
        self.assertNotEqual(svg['sourceSha256'], svg['sha256'])
        for path, source in (('/poster.png', PNG), ('/caption.vtt', CAPTIONS)):
            row = inventory[self.origin + path]
            self.assertEqual(row['sourceSha256'], row['sha256'])
            self.assertEqual(row['sourceSha256'], hashlib.sha256(source).hexdigest())
            self.assertEqual((row['sourceBytes'], row['bytes']), (len(source), len(source)))
        reference = inventory[self.origin + '/mislabelled-image.png']
        self.assertEqual((reference['sourceBytes'], reference['sourceSha256']), (0, None))
        self.assertEqual((reference['bytes'], reference['sha256']), (0, None))
        final = next(event for event in reversed(events) if event['event'] == 'pipeline_progress')
        self.assertEqual(final['media']['bytes'], sum(row['bytes'] for row in inventory.values()
                                                    if row['downloadState'] == 'saved'))

    def test_late_article_retains_previously_classified_stream_reference(self):
        result, events, hits, *_rest = self.collect(True)
        stream = next(row for row in result['resources'] if row['url'] == self.origin + '/extensionless-audio')
        self.assertTrue(any(ref['pageUrl'] == self.origin + '/article' and
                            ref['label'] == 'Listen to the article audio' for ref in stream['references']))
        self.assertTrue(any(ref['pageUrl'] == self.origin + '/' and ref['label'] == 'Stream'
                            for ref in stream['references']))
        final = next(event for event in reversed(events) if event['event'] == 'pipeline_progress')
        pages = final['pages']
        self.assertEqual(pages['discovered'], pages['completed'] + pages['failed'] + pages['skipped'])
        self.assertEqual((pages['active'], pages['queued']), (0, 0))

    def test_slow_home_is_retained_in_deterministic_samples_and_record_order(self):
        result, _events, _hits, *_rest = self.collect(True, mode='samples')
        urls = sorted(url for url, row in result['pages'].items() if row.get('extracted'))
        self.assertGreaterEqual(len(urls), 10)
        self.assertIn('HomeMarker', result['html_samples'][0])
        paths = [re.search(r'FixtureURL:([^ ]+)', html).group(1) for html in result['html_samples']]
        self.assertEqual(paths, [urlparse(url).path for url in urls[:8]])
        self.assertEqual([row['url'] for row in result['page_records']], urls)
        self.assertEqual(result['sample_urls'], urls[:8])

    def test_preferred_and_all_modes_keep_same_inventory_and_limit_variant_fetches(self):
        runs = {}
        for image_mode in ('preferred', 'all'):
            result, _events, hits, *_rest = self.collect(True, mode='variants', image_mode=image_mode)
            inventory = {row['url']: row for row in result['resources']}
            methods = Counter((method, path) for method, path, _when in hits)
            for path in ('/primary.png', '/poster.png', '/icon.png'):
                self.assertEqual(methods['GET', path], 1)
                self.assertEqual(inventory[self.origin + path]['downloadState'], 'saved')
            for path in ('/variant-small.png', '/variant-large.png'):
                self.assertEqual(methods['GET', path], 0 if image_mode == 'preferred' else 1)
                self.assertEqual(inventory[self.origin + path]['downloadState'],
                                 'not-selected' if image_mode == 'preferred' else 'saved')
            runs[image_mode] = set(inventory)
        self.assertEqual(runs['preferred'], runs['all'])

    def test_late_primary_image_promotes_unselected_variant_and_no_images_wins(self):
        result, _events, hits, *_rest = self.collect(True, mode='variants-late')
        inventory = {row['url']: row for row in result['resources']}
        self.assertEqual(inventory[self.origin + '/variant-small.png']['downloadState'], 'saved')
        self.assertEqual(inventory[self.origin + '/variant-large.png']['downloadState'], 'not-selected')
        self.assertEqual(sum(method == 'GET' and path == '/variant-small.png' for method, path, _when in hits), 1)
        result, _events, hits, *_rest = self.collect(True, mode='variants', image_mode='all', download_images=False)
        self.assertTrue(all(row['downloadState'] == 'not-requested' for row in result['resources'] if row['type'] == 'image'))
        self.assertFalse(any(method == 'GET' and path.endswith('.png') for method, path, _when in hits))

    def test_asset_budget_omissions_emit_one_aggregate_capture_warning(self):
        with patch.object(pipeline, 'MAX_ASSET_FILES', 1):
            result, events, _hits, *_rest = self.collect(True, mode='variants', image_mode='all')
        skipped = [row for row in result['resources'] if row['downloadState'] == 'budget-skipped']
        self.assertTrue(skipped)
        warnings = [warning for warning in result['warnings'] if 'asset budget' in warning]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(result['metrics']['assetsBudgetSkipped'], len(skipped))
        self.assertIn(str(len(skipped)) + ' selected resource(s)', warnings[0])
        final = next(event for event in reversed(events) if event['event'] == 'pipeline_progress')
        self.assertGreaterEqual(final['media']['skipped'], len(skipped))

    def test_clean_capture_becomes_partial_when_asset_budget_omits_selected_images(self):
        import crawl_site
        for limits in ({'MAX_ASSET_FILES': 1}, {'MAX_ASSET_BYTES': len(PNG)}):
            with self.subTest(limits=limits):
                Website.reset('budget-clean')
                with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), patch.multiple(pipeline, **limits):
                    manifest = crawl_site.crawl_website_to_vault(self.origin, folder,
                        render_mode='never', delay_sec=0, check_external=True)
                self.assertEqual(manifest['captureStatus'], 'partial')
                warnings = manifest.get('captureWarnings') or manifest.get('warnings') or []
                self.assertEqual(len(warnings), 1)
                self.assertIn('asset budget', warnings[0])
                self.assertTrue(any(row['downloadState'] == 'budget-skipped' for row in manifest['resources']))
                self.assertTrue(all(node['statusCode'] == 200 for node in manifest['nodes']))

    def test_duplicate_redirect_target_prefers_direct_evidence_in_both_completion_orders(self):
        origin = 'https://fixture.example'
        destination = origin + '/destination'
        policy = build_robots_policy('User-agent: *\nAllow: /', 200)
        for direct_first in (True, False):
            with self.subTest(direct_first=direct_first):
                class Dispatcher:
                    def __init__(self, **_options):
                        self.timers = []
                    def __enter__(self):
                        return self
                    def __exit__(self, *_args):
                        for timer in self.timers:
                            timer.join(2)
                    def submit(self, operation, payload, **_options):
                        self_url = payload['url']
                        direct = self_url == destination
                        marker = 'DirectMarker' if direct else 'RedirectMarker'
                        html = f'<html><title>{marker}</title><h1>{marker}</h1></html>'
                        result = {'requested_url': self_url, 'final_url': destination,
                                  'status_code': 200, 'content_type': 'text/html',
                                  'headers': {}, 'html': html, 'raw_bytes': html.encode(),
                                  'error': None, 'redirect_chain': [] if direct else
                                  [{'url': origin + '/', 'status_code': 302}]}
                        future = Future()
                        timer = threading.Timer(.01 if direct == direct_first else .08,
                                                lambda: future.set_result(result))
                        self.timers.append(timer)
                        timer.start()
                        return future
                with tempfile.TemporaryDirectory() as folder, patch('workers.WorkerDispatcher', Dispatcher):
                    result = collect_site(origin, origin, 'fixture.example', {destination: {}},
                        folder, 'fixture.example', 10, False, 'never', 0, {origin: policy},
                        lambda _url: policy, lambda _url: True, lambda *_args, **_data: None)
                    self.assertEqual(set(result['pages']), {destination})
                    chosen = result['pages'][destination]
                    self.assertEqual(chosen['extracted']['title'], 'DirectMarker')
                    self.assertEqual(chosen['redirect_chain'], [], 'Direct target must not inherit redirect health')
                    self.assertEqual(len(result['page_records']), 1)
                    record = result['page_records'][0]
                    self.assertEqual(record['url'], destination)
                    self.assertEqual(record['requestedUrl'], destination)
                    self.assertEqual(record['title'], 'DirectMarker')
                    self.assertEqual({row['url'] for row in result['fetch_rows']}, {origin + '/', destination})
                    receipt = next(row for row in result['fetch_rows'] if row['url'] == destination)
                    self.assertEqual(record['rawSha256'], receipt['rawSha256'])

    def test_serial_dispatcher_has_completed_futures_and_lifecycle_guards(self):
        policy = build_robots_policy('User-agent: *\nAllow: /', 200)
        with SerialDispatcher(min_interval_sec=0) as dispatcher:
            payload = {'url': self.origin + '/audio', 'target_host': '127.0.0.1',
                       'robots_policies': {origin_key(self.origin): policy}}
            future = dispatcher.submit('page-http', payload)
            self.assertTrue(future.done())
            self.assertEqual(future.result()['status_code'], 200)
            self.assertEqual(dispatcher.stats()['active'], 0)
            asset = dispatcher.submit('asset', {**payload, 'url': self.origin + '/mislabelled-image.png',
                                      'allowed_types': ['image', 'transcript']}).result()
            self.assertEqual(asset['resource_type'], 'audio')
            self.assertEqual(asset['error_kind'], 'reference-only')
            self.assertEqual(asset['raw_bytes'], b'')
        dispatcher.close()
        with self.assertRaises(RuntimeError):
            dispatcher.submit('page-http', payload)
        with self.assertRaises(ValueError):
            SerialDispatcher().submit('unsupported', payload)

    def test_full_capture_distinguishes_missing_server_and_transport_errors(self):
        import crawl_site
        Website.reset()
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            manifest = crawl_site.crawl_website_to_vault(self.origin, folder,
                render_mode='never', delay_sec=0, check_external=True)
            nodes = {node['url']: node for node in manifest['nodes'] if node['kind'] != 'external-domain'}
            self.assertEqual(nodes[self.origin + '/missing']['health'], 'broken')
            self.assertEqual(nodes[self.origin + '/unavailable']['health'], 'unavailable')
            self.assertEqual(nodes[self.origin + '/disconnect']['health'], 'unavailable')
            for path in ['/caption.vtt', '/voice.m4a', '/clip.mp4', '/live.mpd', '/extensionless-audio']:
                self.assertNotIn(self.origin + path, nodes)
            site = Path(folder) / 'sites' / manifest['siteId']
            self.assertTrue((site / '_resources.json').is_file())
            self.assertTrue((site / '_resources.md').is_file())
            self.assertTrue(manifest['resources'])

    def test_delayed_fixture_benchmark(self):
        if not BENCHMARK:
            self.skipTest('Enable --benchmark for the delayed serial/parallel comparison')
        rows, fingerprints = [], []
        for parallel in (False, True):
            start = time.monotonic()
            result, events, hits, peak, extracted, retained, artifacts = self.collect(parallel, mode='benchmark')
            elapsed = time.monotonic() - start
            rows.append({'mode': 'parallel' if parallel else 'serial', 'elapsedSec': round(elapsed, 3),
                         'pages': len(result['pages']), 'resources': len(result['resources']),
                         'requests': len(hits), 'peakHttpConcurrency': peak,
                         'pageBodiesExtracted': len(extracted), 'retainedFiles': len(retained)})
            fingerprints.append({'pages': [(url, row['status_code']) for url, row in result['pages'].items()],
                                 'resources': [(row['url'], row['type'], row['downloadState']) for row in result['resources']],
                                 'samples': result['html_samples'],
                                 'records': [record['url'] for record in result['page_records']],
                                 'artifacts': sorted(artifacts.items())})
        self.assertEqual(fingerprints[0], fingerprints[1], 'Serial and parallel modes must retain the same capture')
        self.assertEqual(rows[0]['peakHttpConcurrency'], 1)
        self.assertGreaterEqual(rows[1]['peakHttpConcurrency'], 2)
        report = {'evidenceClass': 'local-delayed-http-fixture', 'rows': rows,
                  'speedup': round(rows[0]['elapsedSec'] / rows[1]['elapsedSec'], 3),
                  'concurrencyMeasurement': 'server application work before response headers or connection close',
                  'scope': 'HTTP-only fixture; no public website or browser speed claim'}
        print(json.dumps(report, sort_keys=True), flush=True)
        if BENCHMARK_OUTPUT:
            Path(BENCHMARK_OUTPUT).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--benchmark-output')
    options, remaining = parser.parse_known_args()
    BENCHMARK, BENCHMARK_OUTPUT = options.benchmark, options.benchmark_output
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
