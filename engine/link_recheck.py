"""Continue saved unchecked targets without recrawling HTML or downloading media."""
from collections import deque
from concurrent.futures import wait, FIRST_COMPLETED, CancelledError
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlparse

from capture_store import CaptureTransaction, files_under, write_json
from provenance import capture_provenance, assert_engine_unchanged
from site_intel import summarize_link_results
from workers import WorkerDispatcher


def _report(health):
    lines = ['# Direct link and resource checks', '',
             f"Observed targets: {health['totalCount']}. Attempted: {health['checkedCount']}. Unchecked: {health['uncheckedCount']}.",
             f"Link checks updated: {health['updatedAt']}. Page capture time is unchanged.", '',
             '403/429 and transport failures remain inconclusive. Requests use HEAD with streamed GET fallback; media bodies are not retained.', '',
             '| URL | Result | HTTP | Reason |', '| :--- | :--- | :--- | :--- |']
    for row in health['results']:
        values = [row['url'], row['status'], row.get('statusCode') or 'No data', row['reason']]
        lines.append('| ' + ' | '.join(str(v).replace('|', '\\|').replace('\n', ' ') for v in values) + ' |')
    return '\n'.join(lines) + '\n'


def continue_link_checks(site_id, vault_dir, emit, *, max_checks=1000, max_seconds=60,
                         dispatcher_class=WorkerDispatcher):
    if not isinstance(site_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,179}', site_id):
        raise ValueError('Invalid saved site ID.')
    with CaptureTransaction(vault_dir) as transaction:
        provenance = capture_provenance({'operation': 'continue-links', 'maxChecks': max_checks, 'maxSeconds': max_seconds})
        active = Path(vault_dir).resolve() / 'sites' / site_id
        if active.is_symlink():
            raise ValueError('Saved capture must not be a symlink.')
        previous = files_under(active)
        if '_site-graph.json' not in previous:
            raise ValueError('Saved capture not found.')
        manifest = json.loads(previous['_site-graph.json'].read_text(encoding='utf-8'))
        if manifest.get('siteId') != site_id:
            raise ValueError('Saved capture identity does not match its folder.')
        rows = manifest.get('linkHealth', {}).get('results', [])
        if not isinstance(rows, list) or len(rows) > 20000 or any(not isinstance(r, dict) or not isinstance(r.get('url'), str) for r in rows):
            raise ValueError('Invalid saved link inventory.')
        targets = deque(sorted({r['url'] for r in rows if r.get('status') == 'unchecked'
                                or r.get('status') == 'broken' and r.get('method') == 'HEAD'}))
        target_count = len(targets)
        staged = transaction.stage / 'sites' / site_id
        staged.mkdir(parents=True)
        for name, file in previous.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
        started = time.monotonic()
        deadline = started + max_seconds
        futures, updates, receipts = {}, {}, {}
        submitted = 0
        emit('phase', phase='crawl', message='Checking remaining saved targets; page content and media are reused.')
        host = urlparse(manifest['origin']).hostname
        policies = {}  # Refresh same-site robots policy for this check session.
        with dispatcher_class(min_interval_sec=.15) as dispatcher:
            while targets or futures:
                while targets and len(futures) < 3 and submitted < max_checks and time.monotonic() < deadline:
                    url = targets.popleft()
                    payload = {'url': url, 'target_host': host, 'robots_policies': dict(policies), 'request_timeout': 3}
                    futures[dispatcher.submit('link', payload, timeout_sec=max(.001, min(8, deadline - time.monotonic())))] = url
                    submitted += 1
                if not futures:
                    break
                done, _ = wait(futures, timeout=.25, return_when=FIRST_COMPLETED)
                for future in done:
                    url = futures.pop(future)
                    try:
                        result = future.result()
                    except CancelledError:
                        raise
                    except Exception as exc:
                        result = {'url': url, 'status': 'unknown', 'statusCode': None,
                                  'attempted': True, 'reason': str(exc)}
                    policies.update(result.pop('discovered_robots_policies', {}) or {})
                    for origin, receipt in (result.pop('robots_receipts', {}) or {}).items():
                        raw = receipt.pop('raw_bytes', b'')
                        digest = hashlib.sha256(raw).hexdigest()
                        if receipt.get('sha256') and receipt['sha256'] != digest:
                            raise ValueError('Inconsistent link-check robots evidence.')
                        relative = '_raw/robots-' + digest + '.txt'
                        (staged / relative).parent.mkdir(parents=True, exist_ok=True)
                        (staged / relative).write_bytes(raw)
                        receipts[origin] = {**receipt, 'rawPath': relative, 'sha256': digest}
                    result['checkedAt'] = datetime.now(timezone.utc).isoformat()
                    updates[url] = result
                inconclusive = sum(r['status'] == 'unknown' for r in updates.values())
                lane = dict(discovered=target_count, completed=len(updates) - inconclusive,
                            active=len(futures), queued=len(targets), failed=inconclusive, skipped=0)
                empty = dict(discovered=0, completed=0, active=0, queued=0, failed=0, skipped=0)
                emit('pipeline_progress', phase='crawl', stage='links', message='Checking remaining saved targets',
                     currentUrl=next(iter(futures.values()), ''), elapsedSec=round(time.monotonic() - started, 2),
                     pages=empty, media=empty, links=lane)
        health = summarize_link_results([updates.get(r['url'], r) for r in rows], max_checks, max_seconds)
        health.update(scope='External destinations and observed media/resources',
                      updatedAt=datetime.now(timezone.utc).isoformat())
        sessions = list(manifest.get('linkCheckSessions', []))
        sessions.append({'updatedAt': health['updatedAt'], 'targetsSubmitted': submitted,
                         'remainingUnchecked': health['uncheckedCount'], 'robotsReceipts': receipts,
                         'provenance': provenance})
        manifest.update(linkHealth=health, linkCheckSessions=sessions)
        for resource in manifest.get('resources', []):
            if resource['url'] in updates:
                row = updates[resource['url']]
                resource.update(checkStatus=row['status'], statusCode=row['statusCode'], checkUpdatedAt=row['checkedAt'])
        summary = json.loads((staged / '_site-summary.json').read_text(encoding='utf-8'))
        summary.update(linkHealth=health, linkCheckSessions=sessions, resources=manifest.get('resources', []))
        write_json(staged / '_site-summary.json', summary)
        write_json(staged / '_link-health.json', health)
        (staged / '_link-health.md').write_text(_report(health), encoding='utf-8')
        resource_file = staged / '_resources.json'
        changed = {'_site-graph.json', '_site-summary.json', '_link-health.json', '_link-health.md'}
        if resource_file.exists():
            data = json.loads(resource_file.read_text(encoding='utf-8'))
            data['resources'] = manifest.get('resources', [])
            write_json(resource_file, data)
            changed.add('_resources.json')
        resource_lines = ['# Media and Resource Inventory', '',
                          f"Link checks updated: {health['updatedAt']}. Page capture time is unchanged.", '',
                          '| Type | URL | Check | Saved file | Source pages |',
                          '| :--- | :--- | :--- | :--- | :--- |']
        for resource in manifest.get('resources', []):
            values = [resource['type'], resource['url'], resource.get('checkStatus', 'unchecked'),
                      resource.get('localPath') or 'Reference only',
                      ', '.join(sorted({r['pageUrl'] for r in resource['references']}))]
            resource_lines.append('| ' + ' | '.join(str(v).replace('|', '\\|').replace('\n', ' ') for v in values) + ' |')
        (staged / '_resources.md').write_text('\n'.join(resource_lines) + '\n', encoding='utf-8')
        changed.add('_resources.md')
        dashboard = staged / '_dashboard.md'
        if dashboard.exists():
            updated_dashboard = re.sub(
                r'^- \[\[sites/' + re.escape(site_id) + r'/_link-health\|[^\n]*$',
                f"- [[sites/{site_id}/_link-health|Link and resource checks]]: {health['checkedCount']}/{health['totalCount']} attempted; {health['uncheckedCount']} unchecked; {len(health['brokenLinks'])} confirmed 404/410 targets. Link checks updated {health['updatedAt']}.",
                dashboard.read_text(encoding='utf-8'), flags=re.MULTILINE)
            if updated_dashboard != dashboard.read_text(encoding='utf-8'):
                dashboard.write_text(updated_dashboard, encoding='utf-8')
                changed.add('_dashboard.md')
        # Page content and its original collection time remain unchanged.
        changed.update(r['rawPath'] for r in receipts.values())
        assert_engine_unchanged(provenance)
        manifest = transaction.commit(manifest, generated_paths=changed)
    emit('complete', siteId=site_id, domain=manifest['domain'], captureStatus=manifest.get('captureStatus', 'partial'),
         manifestPath=f'sites/{site_id}/_site-graph.json', operation='continue-links')
    return manifest
