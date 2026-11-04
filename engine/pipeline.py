"""Coordinate bounded fetch queues; all retained files have one parent writer."""
from collections import deque
from concurrent.futures import wait, FIRST_COMPLETED
import hashlib
from pathlib import Path
import time
from urllib.parse import urldefrag, urlparse

from extractor import LocalAssetDownloader, extract_page_data
from resources import classify_resource
from sitemap import canonicalize_crawl_url, is_same_site_host, url_match_key
from url_safety import MAX_RETRY_AFTER_SEC, note_origin_request, retry_after_seconds, wait_for_origin_pacing
from site_intel import MAX_CRAWL_DELAY_SEC, robots_url_decision

MAX_ASSET_FILES = 500
MAX_ASSET_BYTES = 128 * 1024 * 1024


def _lane():
    return dict(discovered=0, completed=0, active=0, queued=0, failed=0, skipped=0, bytes=0)


def collect_site(origin, target_url, target_host, sitemap_urls, site_root,
                 domain_folder, max_pages, download_images, render_mode,
                 delay_sec, robots_policies, policy_for, allow_resource,
                 emit, *, check_external=True, image_mode='preferred', parallel=True,
                 extract_fn=extract_page_data):
    """Collect pages and related resources while independent queues overlap.

    The dispatcher owns process lifetimes and request leases. Workers return
    bytes; this coordinator alone writes raw artifacts, assets and metadata.
    """
    from workers import WorkerDispatcher
    if image_mode not in ('preferred', 'all'):
        raise ValueError('Image mode must be preferred or all.')
    started = time.monotonic()
    root = Path(site_root)
    raw_dir = root / '_raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    downloader = LocalAssetDownloader(str(root / 'assets'), max_images_total=MAX_ASSET_FILES,
        max_total_bytes=MAX_ASSET_BYTES, allow_url=allow_resource) if download_images else None
    pages, aliases, images, samples, headers = {}, {}, {}, {}, {}
    # One published URL per page. Forms differing only by a trailing slash resolve to the
    # first one registered (the sitemap form wins), and links written in another form are recorded.
    published_forms, form_aliases, link_form_mismatches = {}, {}, {}
    sample_headers = {}
    receipts, records, sources, warnings = [], [], {}, []
    # Warnings mean the capture is incomplete. Findings are broken things the capture found
    # (a page or resource that answers 404 or 410). They do not make the capture partial.
    findings = []
    robots_receipts = {}
    inventory, resource_aliases = {}, {}
    page_queue, asset_queue, link_queue = deque(), deque(), deque()
    seen_pages, scheduled_assets, scheduled_links = set(), set(), set()
    selected_images, asset_budget_skipped = set(), set()
    page_sources = {}
    reclassified_pages = set()
    collapsed_page_requests = 0
    page_futures, asset_futures, link_futures = {}, {}, {}
    link_results = {}
    counts = {name: _lane() for name in ('pages', 'media', 'links')}
    total_page_bytes, saved_resource_bytes, saved_resource_count = 0, 0, 0
    page_budget_used, candidate_requests, media_requests = 0, 0, 0
    last_progress, links_drain_deadline = 0, None

    max_resource_warning = False

    def add_resource(url, kind=None, page_url=None, role='link', label='', language=None, mime=None):
        nonlocal max_resource_warning
        original = url
        url = urldefrag(str(url))[0]
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
        if url not in inventory and len(inventory) >= 20000:
            if not max_resource_warning:
                warnings.append('The 20,000-resource inventory limit was reached; additional references were omitted.')
                max_resource_warning = True
            return None
        resource_aliases.setdefault(url, set()).add(original)
        classification = classify_resource(url, content_type=mime, declared_type=kind)
        observed_kind = kind or classification['type']
        if observed_kind == 'page':
            return None
        entry = inventory.setdefault(url, {
            'id': 'resource-' + hashlib.sha256(url.encode()).hexdigest()[:16],
            'url': url, 'type': observed_kind, 'mimeType': mime,
            'references': [], 'checkStatus': 'unchecked', 'downloadState': 'reference',
            'statusCode': None, 'localPath': None,
            'sourceSha256': None, 'sourceBytes': 0, 'sha256': None, 'bytes': 0,
        })
        if mime:
            entry['mimeType'] = mime
        if page_url:
            reference = {'pageUrl': page_url, 'role': role, 'label': label or '', 'language': language}
            if reference not in entry['references']:
                entry['references'].append(reference)
        return entry

    def resolve_published(url):
        literal = canonicalize_crawl_url(url)
        if not literal:
            return None, None
        key = url_match_key(literal) or literal
        return published_forms.setdefault(key, literal), literal

    def enqueue_page(url, source_page=None, label=''):
        normalized, literal = resolve_published(url)
        if not normalized or not is_same_site_host(urlparse(normalized).hostname or '', target_host):
            return
        if literal != normalized:
            form_aliases[literal] = normalized
            if source_page:
                mismatches = link_form_mismatches.setdefault(source_page, {})
                mismatches[literal] = normalized
        existing = inventory.get(normalized)
        kind = existing['type'] if existing else classify_resource(normalized)['type']
        if kind != 'page':
            entry = add_resource(normalized, kind, source_page, 'sitemap' if not source_page else 'link', label)
            queue_asset(entry)
            if entry:
                enqueue_link(entry['url'])
            return
        if source_page:
            reference = {'pageUrl': source_page, 'label': label}
            if reference not in page_sources.setdefault(normalized, []):
                page_sources[normalized].append(reference)
        if normalized not in seen_pages:
            seen_pages.add(normalized)
            page_queue.append(normalized)

    def enqueue_link(url):
        normalized = urldefrag(str(url))[0]
        if normalized in scheduled_links or not normalized.startswith(('http://', 'https://')):
            return
        scheduled_links.add(normalized)
        link_queue.append(normalized)

    def link_from_fetch(url, result):
        scheduled_links.add(url)
        status = result.get('status_code') or None
        error = None if result.get('error_kind') == 'reference-only' else result.get('error')
        kind = 'ok' if status and 200 <= status < 400 and not error else 'broken' if status in (404, 410) else 'server-error' if status and status >= 500 else 'unknown'
        link_results[url] = {'url': url, 'finalUrl': result.get('final_url') or url,
            'status': kind, 'statusCode': status, 'attempted': True,
            'reason': error or (f'HTTP {status}' if status else 'No HTTP response'),
            'redirectChain': result.get('redirect_chain') or [], 'method': 'GET'}

    def queue_asset(entry):
        if not entry or entry['url'] in scheduled_assets:
            return
        if entry['type'] == 'image' and not download_images:
            entry['downloadState'] = 'not-requested'
            return
        if entry['type'] == 'image' and image_mode == 'preferred':
            if any(ref['role'] == 'poster' or 'icon' in ref['role'].lower() or
                   'logo' in ref['role'].lower() for ref in entry['references']):
                selected_images.add(entry['url'])
            if entry['url'] not in selected_images:
                entry['downloadState'] = 'not-selected'
                return
        if entry['type'] not in ('image', 'transcript'):
            return
        scheduled_assets.add(entry['url'])
        entry['downloadState'] = 'queued'
        asset_queue.append(entry['url'])

    def mark_asset_budget(url, entry=None):
        if url not in asset_budget_skipped:
            asset_budget_skipped.add(url)
            if url in scheduled_assets:
                counts['media']['skipped'] += 1
        if entry is not None:
            entry.update(downloadState='budget-skipped', downloadReason='Shared asset budget reached.')

    def progress(stage='crawl', force=False):
        nonlocal last_progress
        now = time.monotonic()
        if not force and now - last_progress < .25:
            return
        counts['pages'].update(discovered=len(seen_pages) - len(reclassified_pages) - collapsed_page_requests, completed=sum(bool(page.get('extracted')) for page in pages.values()), failed=sum(not bool(page.get('extracted')) for page in pages.values()), active=len(page_futures), queued=len(page_queue))
        counts['media'].update(discovered=len(scheduled_assets), active=len(asset_futures), queued=len(asset_queue))
        active_links = {job['url'] for job in link_futures.values()} - link_results.keys()
        pending_links = set(link_queue) - link_results.keys() - active_links
        counts['links'].update(discovered=len(scheduled_links), active=len(active_links), queued=len(pending_links), completed=sum(bool(r.get('attempted')) and r.get('status') != 'unknown' for r in link_results.values()), failed=sum(bool(r.get('attempted')) and r.get('status') == 'unknown' for r in link_results.values()), skipped=sum(not r.get('attempted') for r in link_results.values()))
        active = next(iter(page_futures.values()), None) or next(iter(asset_futures.values()), None) or next(iter(link_futures.values()), None)
        current_url = active.get('url', '') if isinstance(active, dict) else ''
        message = 'Collecting pages, media and link results' if stage == 'crawl' else 'Finishing media and link checks'
        emit('pipeline_progress', phase='crawl', stage=stage, message=message,
             currentUrl=current_url, elapsedSec=round(now - started, 2), **counts)
        last_progress = now

    def save_receipt(url, result, decision, extracted=None):
        nonlocal total_page_bytes
        raw = result.get('raw_bytes') or b''
        text = (result.get('html') or '').encode('utf-8')
        total_page_bytes += len(raw) + (len(text) if text != raw else 0)
        if total_page_bytes > 128 * 1024 * 1024:
            raise RuntimeError('The 128 MB page evidence budget was reached. Previous capture preserved.')
        digest = hashlib.sha256(raw).hexdigest() if raw else None
        raw_path = f'_raw/{digest}.html' if raw else None
        if raw_path:
            (root / raw_path).write_bytes(raw)
        text_digest = hashlib.sha256(text).hexdigest() if text and text != raw else None
        text_path = f'_raw/{text_digest}.utf8.txt' if text_digest else None
        if text_path:
            (root / text_path).write_bytes(text)
        row = {'url': url, 'finalUrl': canonicalize_crawl_url(result.get('final_url') or url) or url, 'path': urlparse(url).path, 'attempted': True,
            'statusCode': result.get('status_code'), 'responseTimeMs': result.get('response_time_ms', 0),
            'htmlBytes': len(raw), 'rawPath': raw_path, 'rawSha256': digest,
            'rawKind': result.get('raw_kind', 'http-response-decoded'),
            'textPath': text_path, 'textSha256': text_digest,
            'renderUsed': result.get('render_used', False), 'robotsPolicy': decision['status'],
            'redirectChain': result.get('redirect_chain', []), 'error': result.get('error'),
            'blockedRequests': result.get('blocked_requests', []), 'visibleChars': (extracted or {}).get('visible_chars', 0)}
        receipts.append(row)
        if raw_path:
            sources[url] = {'rawPath': text_path or raw_path, 'rawSha256': text_digest or digest,
                'rawKind': 'decoded-text' if text_path else row['rawKind'],
                'parentRawPath': raw_path if text_path else None,
                'parentRawSha256': digest if text_path else None,
                'statusCode': result.get('status_code'), 'robotsPolicy': decision['status']}
        return row

    extract_failures = []
    extract_successes = 0

    def accept_page(url, result, decision):
        nonlocal page_budget_used, collapsed_page_requests, extract_successes
        status = result.get('status_code') or 0
        classification = classify_resource(result.get('final_url') or url,
            result.get('content_type'), result.get('content_disposition'))
        if 200 <= status < 300 and classification['type'] != 'page':
            page_budget_used -= 1
            reclassified_pages.add(url)
            entry = add_resource(url, classification['type'], role='response', mime=result.get('content_type'))
            if entry:
                for reference in page_sources.get(url, []):
                    add_resource(url, classification['type'], reference['pageUrl'], 'link', reference['label'], mime=result.get('content_type'))
                entry.update(statusCode=status, checkStatus='ok', error=None)
                link_from_fetch(url, result)
                queue_asset(entry)
            return
        final = canonicalize_crawl_url(result.get('final_url') or url) or url
        if not is_same_site_host(urlparse(final).hostname or '', target_host):
            result = {**result, 'error': 'Final document is outside the selected website.', 'error_kind': 'policy', 'html': '', 'raw_bytes': b''}
            final = url
        if final != url:
            aliases[url] = final
        effective = final
        extracted = None
        if not result.get('error') and 200 <= status < 400 and result.get('html'):
            try:
                extracted = extract_fn(result['html'], effective, target_host, result.get('headers'))
                extract_successes += 1
            except Exception as exc:  # One malformed page must not end the whole capture.
                extract_failures.append(exc)
                result = {**result, 'error': f'Page content could not be parsed ({type(exc).__name__}).', 'error_kind': 'extract'}
                extracted = None
        existing_source = sources.get(effective)
        row = save_receipt(url, result, decision, extracted)
        existing = pages.get(effective)
        if existing:
            collapsed_page_requests += 1
            old_priority = (not bool(existing.get('extracted')), existing.get('requested_url') != effective, existing.get('requested_url') or effective)
            new_priority = (not bool(extracted), url != effective, url)
            if old_priority <= new_priority:
                if existing_source is not None:
                    sources[effective] = existing_source
                return
            records[:] = [record for record in records if record['url'] != effective]
        if extracted:
            if not headers and (url == home or effective == home):
                headers.update(result.get('headers') or {})
            samples[effective] = result['html']
            sample_headers[effective] = dict(result.get('headers') or {})
            if len(samples) > 8:
                evicted = max(samples, key=lambda sample_url: (sample_url != home, sample_url))
                samples.pop(evicted)
                sample_headers.pop(evicted, None)
            sources[effective] = sources.get(url, {})
            records.append({'url': effective, 'requestedUrl': url, 'rawPath': row['rawPath'], 'rawSha256': row['rawSha256'],
                'rawKind': row['rawKind'], 'textPath': row['textPath'], 'textSha256': row['textSha256'],
                'statusCode': status, 'title': extracted.get('title', ''), 'markdown': extracted.get('markdown', ''), 'extracted': extracted})
            selected_images.update(urldefrag(str(image['url']))[0] for image in extracted.get('images', []))
            for reference in extracted.get('resources', []):
                entry = add_resource(reference['url'], reference['type'], effective, reference.get('role', 'link'),
                    reference.get('label', ''), reference.get('language'), reference.get('mimeType'))
                queue_asset(entry)
                if entry:
                    enqueue_link(entry['url'])
            for image in extracted.get('images', []):
                entry = add_resource(image['url'], 'image', effective, 'image', image.get('alt', ''))
                queue_asset(entry)
                if entry:
                    enqueue_link(entry['url'])
            for svg in extracted.get('inline_svgs', []):
                if downloader:
                    downloader.max_total_bytes = max(0, MAX_ASSET_BYTES - saved_resource_bytes)
                    downloader.max_images_total = max(0, MAX_ASSET_FILES - saved_resource_count)
                    filename = downloader.save_inline_svg(svg['pseudo_url'], svg['filename'], svg['svg_xml'])
                    images[svg['pseudo_url']] = filename
                    if not filename:
                        if 'limit' in downloader.errors.get(svg['pseudo_url'], '').lower():
                            mark_asset_budget(svg['pseudo_url'])
                        else:
                            warnings.append(f"{effective}: an inline image was not saved because of safety or resource limits.")
            for link in extracted.get('internal_links', []):
                enqueue_page(link['url'], effective, link.get('anchor', ''))
            for link in extracted.get('external_links', []):
                enqueue_link(link['url'])
            counts['pages']['completed'] += 1
        else:
            counts['pages']['failed'] += 1
            (findings if status in (404, 410) else warnings).append(f"{url}: {result.get('error') or 'HTTP ' + str(status)}")
        if result.get('blocked_requests'):
            warnings.append(f'{url}: browser rendering excluded background or out-of-scope resources; content may be incomplete.')
        pages[effective] = {'url': effective, 'requested_url': url, 'final_url': final, 'status_code': status,
            'response_time_ms': result.get('response_time_ms', 0), 'ttfb_ms': result.get('ttfb_ms', 0), 'fetch_duration_ms': result.get('fetch_duration_ms', 0), 'redirect_hops': result.get('redirect_hops', 0), 'html_bytes': result.get('html_bytes', 0),
            'error': result.get('error') or (None if extracted else f'HTTP {status}'),
            'error_kind': result.get('error_kind'), 'redirect_chain': result.get('redirect_chain', []),
            'render_used': result.get('render_used', False), 'is_spa': result.get('is_spa', False),
            'in_sitemap': effective in sitemap_urls or url in sitemap_urls,
            'sitemap_meta': sitemap_urls.get(effective) or sitemap_urls.get(url),
            'extracted': extracted, 'local_images': []}

    home = canonicalize_crawl_url(origin + '/') or origin + '/'
    for url in sitemap_urls:
        resolve_published(url)
    enqueue_page(home)
    enqueue_page(target_url)
    for url in sitemap_urls:
        enqueue_page(url)
    for entry in list(inventory.values()):
        queue_asset(entry)
        enqueue_link(entry['url'])
    from contextlib import nullcontext
    # Politeness: honour the site's Crawl-delay and back off when it answers 429 or 503.
    target_policy = policy_for(home) or {}
    asked_delay = target_policy.get('crawlDelaySec')
    slow_sec = min(float(asked_delay), MAX_CRAWL_DELAY_SEC) if isinstance(asked_delay, (int, float)) and asked_delay > 0 else 0.0
    if slow_sec:
        warnings.append(f"robots.txt asks for {asked_delay:g} s between requests, so this capture sends one request at a time to the site, {slow_sec:g} s apart."
                        + (f" Values above {MAX_CRAWL_DELAY_SEC:g} s are treated as {MAX_CRAWL_DELAY_SEC:g} s." if asked_delay > MAX_CRAWL_DELAY_SEC else ''))
    dispatcher_options = {'min_interval_sec': max(delay_sec, slow_sec)}
    if slow_sec:
        dispatcher_options['per_origin'] = 1
    on_site = lambda candidate: is_same_site_host(urlparse(candidate).hostname or '', target_host)
    politeness = {'resume_at': 0.0, 'hits': 0, 'halted': False}
    rate_limit_retried = set()

    def site_ready():
        """Whether another request to the captured site may start now."""
        if time.monotonic() < politeness['resume_at']:
            return False
        if slow_sec:
            return not any(on_site(job['url']) for bucket in (page_futures, asset_futures, link_futures) for job in bucket.values())
        return True

    # Lease waits for a slow site count against the job deadline, so give each job room for its hops.
    page_timeout, asset_timeout, link_timeout = 30 + 6 * slow_sec, 20 + 2 * slow_sec, 8 + 2 * slow_sec
    # A serial mode exists for reproducible benchmarks and isolated fault injection.
    from pipeline_serial import SerialDispatcher
    dispatcher_class = WorkerDispatcher if parallel else SerialDispatcher
    if slow_sec:
        wait_for_origin_pacing(home)  # the sitemap phase's last request still counts
    with dispatcher_class(**dispatcher_options) as dispatcher:
        with dispatcher.parent_requests() if hasattr(dispatcher, 'parent_requests') else nullcontext():
            while True:
                while page_queue and len(page_futures) < 4 and page_budget_used < max_pages and candidate_requests < max_pages * 4 and site_ready():
                    url = page_queue.popleft()
                    decision = robots_url_decision(policy_for(url), url)
                    if not decision['allowed']:
                        receipts.append({'url': url, 'path': urlparse(url).path, 'statusCode': None, 'attempted': False, 'robotsPolicy': decision['status'], 'error': decision['reason'], 'rawPath': None, 'rawSha256': None})
                        warnings.append(f"{url}: not fetched ({decision['reason']}).")
                        counts['pages']['skipped'] += 1
                        continue
                    page_budget_used += 1
                    candidate_requests += 1
                    payload = {'url': url, 'target_host': target_host, 'robots_policies': dict(robots_policies), 'render_mode': 'always' if render_mode == 'always' else 'never'}
                    operation = 'render' if render_mode == 'always' else 'page-http'
                    future = dispatcher.submit(operation, payload, timeout_sec=page_timeout)
                    page_futures[future] = {'url': url, 'decision': decision, 'operation': operation}
                while asset_queue and len(asset_futures) < 2:
                    if on_site(asset_queue[0]) and not site_ready():
                        break
                    url = asset_queue.popleft()
                    entry = inventory[url]
                    if media_requests >= MAX_ASSET_FILES or saved_resource_count + (downloader.downloaded_count if downloader else 0) + len(asset_futures) >= MAX_ASSET_FILES or saved_resource_bytes + (downloader.total_bytes if downloader else 0) >= MAX_ASSET_BYTES:
                        mark_asset_budget(url, entry)
                        continue
                    media_requests += 1
                    payload = {'url': url, 'target_host': target_host, 'robots_policies': dict(robots_policies), 'allowed_types': ['image', 'transcript'], 'max_bytes': min(1024 * 1024 if entry['type'] == 'transcript' else 12 * 1024 * 1024, max(0, MAX_ASSET_BYTES - saved_resource_bytes - (downloader.total_bytes if downloader else 0)))}
                    asset_futures[dispatcher.submit('asset', payload, timeout_sec=asset_timeout)] = {'url': url}
                    entry['downloadState'] = 'fetching'
                if not page_futures and (not page_queue or page_budget_used >= max_pages or candidate_requests >= max_pages * 4):
                    if links_drain_deadline is None:
                        links_drain_deadline = time.monotonic() + 30
                link_slots = len(link_queue)
                while link_queue and len(link_futures) < 3 and link_slots:
                    link_slots -= 1
                    url = link_queue.popleft()
                    if url in link_results:
                        continue
                    if url in scheduled_assets and inventory.get(url, {}).get('downloadState') in ('queued', 'fetching'):
                        link_queue.append(url)
                        continue
                    if not check_external or len(link_results) + len(link_futures) >= 1000 or links_drain_deadline is not None and time.monotonic() >= links_drain_deadline:
                        link_results[url] = {'url': url, 'status': 'unchecked', 'statusCode': None, 'attempted': False, 'reason': 'Destination checks disabled.' if not check_external else 'Link-check budget reached.', 'finalUrl': url, 'redirectChain': [], 'method': None}
                        counts['links']['skipped'] += 1
                        continue
                    if on_site(url) and not site_ready() and not (links_drain_deadline is not None and time.monotonic() >= links_drain_deadline):
                        link_queue.append(url)
                        continue
                    if is_same_site_host(urlparse(url).hostname or '', target_host) and not robots_url_decision(policy_for(url), url)['allowed']:
                        link_results[url] = {'url': url, 'finalUrl': url, 'status': 'unchecked', 'statusCode': None, 'attempted': False, 'reason': 'Robots policy refused the resource.', 'redirectChain': [], 'method': None}
                        counts['links']['skipped'] += 1
                        continue
                    payload = {'url': url, 'target_host': target_host, 'robots_policies': dict(robots_policies), 'request_timeout': 3}
                    link_futures[dispatcher.submit('link', payload, timeout_sec=link_timeout)] = {'url': url}
                all_futures = set(page_futures) | set(asset_futures) | set(link_futures)
                progress('draining' if links_drain_deadline else 'crawl')
                if not all_futures:
                    if page_queue and page_budget_used < max_pages and candidate_requests < max_pages * 4 or asset_queue or link_queue:
                        time.sleep(.05 if time.monotonic() < politeness['resume_at'] else 0)
                        continue
                    break
                completed, _ = wait(all_futures, timeout=.25, return_when=FIRST_COMPLETED)
                for future in completed:
                    bucket = page_futures if future in page_futures else asset_futures if future in asset_futures else link_futures
                    job = bucket.pop(future)
                    url = job['url']
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {'url': url, 'final_url': url, 'status_code': None, 'error': str(exc), 'error_kind': 'timeout' if 'deadline' in str(exc).lower() else 'worker', 'html': '', 'raw_bytes': b''}
                    robots_policies.update(result.pop('discovered_robots_policies', {}) or {})
                    for policy_origin, receipt in (result.pop('robots_receipts', {}) or {}).items():
                        raw = receipt.get('raw_bytes') or b''
                        digest = hashlib.sha256(raw).hexdigest()
                        if receipt.get('sha256') and receipt['sha256'] != digest:
                            raise RuntimeError('A worker returned inconsistent robots evidence. Previous capture preserved.')
                        relative = f'_raw/robots-{digest}.txt'
                        (root / relative).write_bytes(raw)
                        robots_receipts[policy_origin] = {key: value for key, value in receipt.items() if key != 'raw_bytes'}
                        robots_receipts[policy_origin].update(rawPath=relative, sha256=digest)
                    if bucket is page_futures:
                        status = result.get('status_code')
                        if status in (429, 503) and on_site(result.get('final_url') or url):
                            headers = result.get('headers') or {}
                            explicit = status == 429 or any(str(key).lower() == 'retry-after' for key in headers)
                            # 429 or Retry-After is an explicit request to slow down. A bare 503 is often one
                            # broken page, so it is retried once later without pausing the whole site.
                            wait_sec = retry_after_seconds(headers, default=30.0) if explicit else 0.0
                            if explicit:
                                politeness['hits'] += 1
                                politeness['resume_at'] = max(politeness['resume_at'], time.monotonic() + min(wait_sec, MAX_RETRY_AFTER_SEC))
                            if explicit and (politeness['hits'] >= 3 or wait_sec > MAX_RETRY_AFTER_SEC) and not politeness['halted']:
                                politeness['halted'] = True
                                warnings.append(f"The site answered HTTP {status} and asked us to slow down, so the capture stopped requesting new pages. "
                                                "Try again later or raise the delay between requests.")
                                for skipped in page_queue:
                                    receipts.append({'url': skipped, 'path': urlparse(skipped).path, 'statusCode': None, 'attempted': False,
                                                     'robotsPolicy': robots_url_decision(policy_for(skipped), skipped)['status'],
                                                     'error': 'Not requested: the site was rate limiting the capture.', 'rawPath': None, 'rawSha256': None})
                                    counts['pages']['skipped'] += 1
                                page_queue.clear()
                            elif not politeness['halted'] and url not in rate_limit_retried:
                                rate_limit_retried.add(url)
                                warnings.append(f"{url}: HTTP {status}, " + (f"pausing {min(wait_sec, MAX_RETRY_AFTER_SEC):g} s before trying it once more." if explicit else "trying it once more later."))
                                page_budget_used -= 1
                                page_queue.append(url)
                                continue
                        if job['operation'] == 'page-http' and render_mode == 'auto' and result.get('is_spa') and not result.get('error'):
                            payload = {'url': url, 'target_host': target_host, 'robots_policies': dict(robots_policies), 'render_mode': 'always', 'prior_http': result}
                            page_futures[dispatcher.submit('render', payload, timeout_sec=30)] = {**job, 'operation': 'render'}
                        else:
                            accept_page(url, result, job['decision'])
                    elif bucket is asset_futures:
                        entry = inventory[url]
                        classification = classify_resource(result.get('final_url') or url, result.get('content_type'), result.get('content_disposition'))
                        if result.get('content_type'):
                            entry.update(type=classification['type'] if classification['type'] != 'page' else entry['type'], mimeType=result['content_type'])
                        entry.update(statusCode=result.get('status_code'), error=result.get('error'))
                        link_from_fetch(url, result)
                        raw = result.get('raw_bytes') or b''
                        entry.update(sourceBytes=len(raw),
                                     sourceSha256=hashlib.sha256(raw).hexdigest() if raw else None,
                                     bytes=0, sha256=None)
                        retained_file = None
                        filename = None
                        storage_budget_exhausted = bool(raw) and (
                            saved_resource_count + (downloader.downloaded_count if downloader else 0) >= MAX_ASSET_FILES or
                            saved_resource_bytes + (downloader.total_bytes if downloader else 0) + len(raw) > MAX_ASSET_BYTES)
                        if entry['type'] == 'image' and downloader and saved_resource_bytes + downloader.total_bytes + len(raw) <= MAX_ASSET_BYTES:
                            downloader.max_total_bytes = max(0, MAX_ASSET_BYTES - saved_resource_bytes)
                            downloader.max_images_total = max(0, MAX_ASSET_FILES - saved_resource_count)
                            filename = downloader.save_download_result(url, result)
                            if filename:
                                entry['localPath'] = f'sites/{domain_folder}/assets/{filename}'
                                retained_file = root / 'assets' / filename
                                for original in resource_aliases.get(url, {url}):
                                    images[original] = filename
                        elif entry['type'] == 'transcript' and not result.get('error') and raw and saved_resource_count + (downloader.downloaded_count if downloader else 0) < MAX_ASSET_FILES and saved_resource_bytes + (downloader.total_bytes if downloader else 0) + len(raw) <= MAX_ASSET_BYTES:
                            suffix = Path(urlparse(url).path).suffix.lower()
                            suffix = suffix if suffix in ('.vtt', '.srt', '.ttml') else '.txt'
                            relative = 'assets/transcripts/' + hashlib.sha256(url.encode()).hexdigest()[:20] + suffix
                            (root / relative).parent.mkdir(parents=True, exist_ok=True)
                            (root / relative).write_bytes(raw)
                            entry['localPath'] = f'sites/{domain_folder}/{relative}'
                            retained_file = root / relative
                            saved_resource_bytes += len(raw)
                            saved_resource_count += 1
                        if entry.get('localPath'):
                            retained_bytes = retained_file.read_bytes()
                            entry.update(bytes=len(retained_bytes),
                                         sha256=hashlib.sha256(retained_bytes).hexdigest())
                            entry['downloadState'] = 'saved'
                            counts['media']['completed'] += 1
                            counts['media']['bytes'] += len(retained_bytes)
                        else:
                            if result.get('error_kind') == 'reference-only':
                                entry.update(downloadState='reference', downloadReason=result.get('error'), error=None)
                                counts['media']['skipped'] += 1
                                continue
                            writer_error = downloader.errors.get(url, '') if downloader else ''
                            if result.get('error_kind') == 'size-limit' or 'limit' in writer_error.lower() or storage_budget_exhausted:
                                mark_asset_budget(url, entry)
                                continue
                            entry['downloadState'] = 'unavailable'
                            counts['media']['failed'] += 1
                            missing = (result.get('status_code') or entry.get('statusCode')) in (404, 410)
                            (findings if missing else warnings).append(f"{url}: resource was not saved ({entry.get('error') or (downloader.errors.get(url) if downloader else None) or 'unsupported response or byte budget'}).")
                    else:
                        if 'status' not in result:
                            result = {'url': url, 'finalUrl': url, 'status': 'unknown', 'statusCode': result.get('status_code'), 'attempted': True, 'reason': result.get('error') or 'Worker failed.', 'redirectChain': [], 'method': None}
                        link_results[url] = result

            if page_queue:
                warnings.append(f'The page limit left {len(page_queue)} discovered page candidates unvisited.')
                counts['pages']['skipped'] += len(page_queue)
                page_queue.clear()
            progress('settled', True)
    if slow_sec:
        note_origin_request(home)  # the workers' last request counts toward the next main-process one
    for entry in inventory.values():
        check = link_results.get(entry['url'])
        if check:
            entry.update(statusCode=check.get('statusCode'), checkStatus=check['status'])
    for url, data in pages.items():
        extracted = data.get('extracted') or {}
        data['local_images'] = list(dict.fromkeys(f'sites/{domain_folder}/assets/{images[item["url"]]}' for item in extracted.get('images', []) + [{'url': s['pseudo_url']} for s in extracted.get('inline_svgs', [])] if images.get(item['url'])))
    if downloader:
        downloader.max_total_bytes = max(0, MAX_ASSET_BYTES - saved_resource_bytes)
        downloader.max_images_total = max(0, MAX_ASSET_FILES - saved_resource_count)
    if asset_budget_skipped:
        warnings.append(f'The asset budget left {len(asset_budget_skipped)} selected resource(s) without local copies. Limits: {MAX_ASSET_FILES} resource fetches or saved files, {MAX_ASSET_BYTES} total bytes, plus per-file byte limits. References remain in the resource inventory.')
    # Canonical ordering makes graph layout and drift independent of completion order.
    ordered_pages = dict(sorted(pages.items(), key=lambda item: (item[0] != home, item[0])))
    ordered_resources = sorted(inventory.values(), key=lambda entry: entry['url'])
    for entry in ordered_resources:
        entry['references'].sort(key=lambda ref: (ref['pageUrl'], ref['role'], ref.get('label') or '', ref.get('language') or ''))
    ordered_checks = [link_results[url] for url in sorted(link_results)]
    sample_urls = sorted(samples, key=lambda sample_url: (sample_url != home, sample_url))
    if extract_failures and not extract_successes:
        # Every page failed to parse: the extractor itself is broken. Keep the previous capture.
        raise extract_failures[0]
    return {'pages': ordered_pages, 'aliases': aliases, 'images': images,
        'html_samples': [samples[url] for url in sample_urls], 'sample_urls': sample_urls,
        'sample_headers': {url: sample_headers.get(url, {}) for url in sample_urls},
        'home_headers': headers, 'fetch_rows': sorted(receipts, key=lambda row: row['url']),
        'page_records': sorted(records, key=lambda record: (record['url'] != home, record['url'], record.get('rawSha256') or '')), 'source_artifacts': sources, 'warnings': warnings, 'findings': findings,
        'resources': ordered_resources, 'link_results': ordered_checks, 'downloader': downloader, 'robots_receipts': robots_receipts,
        'form_aliases': form_aliases, 'link_form_mismatches': link_form_mismatches,
        'metrics': {'elapsedSec': round(time.monotonic() - started, 3), 'pages': len(ordered_pages),
                    'resources': len(ordered_resources), 'imagesBytes': (downloader.total_bytes if downloader else 0),
                    'transcriptBytes': saved_resource_bytes, 'transcriptsSaved': saved_resource_count,
                    'assetsBudgetSkipped': len(asset_budget_skipped)}}
