"""Typed public website resources and bounded asset retrieval, without file writes."""
from __future__ import annotations

from email.message import Message
import hashlib
from pathlib import PurePosixPath
import time
from urllib.parse import unquote, urljoin, urlparse
from requests.exceptions import Timeout

from url_safety import DEFAULT_REQUEST_HEADERS, safe_requests_session


_EXTENSIONS = {
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.avif', '.bmp', '.ico', '.tif', '.tiff'},
    'audio': {'.mp3', '.wav', '.ogg', '.oga', '.m4a', '.aac', '.flac', '.opus', '.aiff', '.aif'},
    'video': {'.mp4', '.m4v', '.mov', '.avi', '.webm', '.mkv', '.ogv', '.m3u8', '.m3u', '.mpd', '.ts'},
    'transcript': {'.vtt', '.srt', '.ttml', '.dfxp', '.sbv', '.ass', '.ssa'},
    'document': {'.pdf', '.zip', '.rar', '.7z', '.tar', '.gz', '.csv', '.xlsx', '.xls', '.doc', '.docx', '.ppt', '.pptx', '.odt', '.epub', '.rtf', '.txt', '.md'},
    'font': {'.woff', '.woff2', '.ttf', '.otf', '.eot'},
    'stylesheet': {'.css'},
    'script': {'.js', '.mjs', '.cjs'},
    'other': {'.xml', '.json', '.map', '.webmanifest', '.wasm'},
}
_MIMES = {
    'text/vtt': 'transcript', 'application/x-subrip': 'transcript',
    'application/ttml+xml': 'transcript', 'application/dfxp+xml': 'transcript',
    'application/vnd.apple.mpegurl': 'video', 'application/x-mpegurl': 'video',
    'audio/mpegurl': 'video', 'audio/x-mpegurl': 'video', 'application/dash+xml': 'video',
    'application/pdf': 'document', 'text/plain': 'document', 'text/markdown': 'document',
    'text/csv': 'document', 'application/rtf': 'document', 'application/zip': 'document',
    'application/epub+zip': 'document', 'application/msword': 'document',
    'application/vnd.ms-excel': 'document', 'application/vnd.ms-powerpoint': 'document',
    'text/css': 'stylesheet', 'text/javascript': 'script', 'application/javascript': 'script',
    'application/x-javascript': 'script', 'application/json': 'other',
    'application/xml': 'other', 'text/xml': 'other', 'application/wasm': 'other',
    'application/vnd.ms-fontobject': 'font', 'application/font-woff': 'font',
}


def _extension_type(path: str):
    extension = PurePosixPath(unquote(path or '').lower()).suffix
    return next((kind for kind, extensions in _EXTENSIONS.items() if extension in extensions), None)


def classify_resource(url: str, content_type: str | None = None,
                      content_disposition: str | None = None,
                      declared_type: str | None = None) -> dict:
    """Classify a response from headers first, then a declared type or URL hint.

    Unknown extensionless links remain page candidates until response headers are
    available. A /watch or /audio HTML landing page remains an HTML page.
    """
    mime = (content_type or '').split(';', 1)[0].strip().lower()
    disposition = Message()
    if content_disposition:
        disposition['Content-Disposition'] = content_disposition
    attachment = disposition.get_content_disposition() == 'attachment'
    filename = disposition.get_filename() or ''
    hint = _extension_type(filename) or _extension_type(urlparse(url).path)
    def result(kind, confidence, reason):
        return {'type': kind, 'mimeType': mime or None, 'confidence': confidence, 'reason': reason}
    if attachment:
        observed = classify_resource(url, content_type=mime)['type'] if mime else None
        kind = observed if observed not in (None, 'page', 'other') else hint or 'document'
        return result(kind, 'header', 'Response declares an attachment')
    if mime in ('text/html', 'application/xhtml+xml'):
        return result('page', 'header', 'Response is HTML')
    if mime in _MIMES:
        # Generic text can contain a declared caption file; preserve the more specific URL hint.
        kind = hint if mime == 'text/plain' and hint in ('transcript', 'audio', 'video') else _MIMES[mime]
        return result(kind, 'header', 'Response content type')
    if mime.startswith('image/'):
        return result('image', 'header', 'Response image content type')
    if mime.startswith('audio/'):
        return result('audio', 'header', 'Response audio content type')
    if mime.startswith('video/'):
        return result('video', 'header', 'Response video content type')
    if mime.startswith('font/'):
        return result('font', 'header', 'Response font content type')
    if mime.startswith('application/vnd.openxmlformats-officedocument') or mime.startswith('application/vnd.oasis.opendocument'):
        return result('document', 'header', 'Response office document content type')
    if mime == 'application/octet-stream':
        return result(hint or 'other', 'header-and-url', 'Binary response with filename or URL hint')
    if mime:
        return result('other', 'header', 'Non-HTML response content type')
    if declared_type:
        declared = declared_type.lower().strip()
        if declared in ('document', 'other') and hint:
            return result(hint, 'url-hint', 'Specific URL extension refines a generic download declaration')
        if declared in _EXTENSIONS or declared == 'page':
            return result(declared, 'declared', 'Published element or link type')
        classified = classify_resource(url, content_type=declared)
        if classified['type'] != 'other':
            return {**classified, 'confidence': 'declared', 'reason': 'Published MIME hint'}
    if hint:
        return result(hint, 'url-hint', 'URL extension; response has not been checked')
    return result('page', 'candidate', 'No non-HTML evidence before a response')


def srcset_urls(value):
    """Read URL tokens without treating embedded data URL commas as delimiters."""
    remaining = str(value or '').strip()
    while remaining:
        remaining = remaining.lstrip(' ,\t\r\n')
        if not remaining:
            break
        pieces = remaining.split(None, 1)
        token = pieces[0]
        yield token.rstrip(',')
        if token.endswith(','):
            remaining = pieces[1] if len(pieces) > 1 else ''
        elif len(pieces) > 1 and ',' in pieces[1]:
            remaining = pieces[1].split(',', 1)[1]
        else:
            break


def extract_resource_references(soup, page_url: str) -> list[dict]:
    """Retain published media, downloads, and support files without downloading them.

    Entries represent a source page and a role, so one poster can remain associated
    with several videos. MIME values here are published hints, not observed headers.
    """
    resources, seen = [], set()

    def add(tag, value, role, declared=None, label=None, language=None):
        value = str(value or '').strip()
        if not value or value.startswith(('#', 'data:', 'blob:', 'javascript:')):
            return
        url = urljoin(page_url, value)
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ('https', 'http') or not parsed.hostname:
            return
        mime = str(tag.get('type') or '').strip() or None
        if role == 'poster' or (mime and '/' not in mime):
            mime = None
        classification = classify_resource(url, declared_type=mime or declared)
        if classification['type'] == 'page' and declared:
            classification = classify_resource(url, declared_type=declared)
        if classification['type'] == 'page':
            return
        label = label or tag.get('aria-label') or tag.get('title') or tag.get('alt') or tag.get_text(' ', strip=True)
        if not label and tag.name in ('source', 'track'):
            owner = tag.find_parent(['audio', 'video'])
            if owner is not None:
                label = owner.get('aria-label') or owner.get('title')
        language = language or tag.get('srclang') or tag.get('hreflang') or tag.get('lang')
        key = (url, role, language or '', label or '')
        if key in seen:
            return
        seen.add(key)
        resources.append({'url': url, 'type': classification['type'], 'sourcePage': page_url,
                          'role': role, 'label': str(label or '')[:240],
                          'language': str(language) if language else None,
                          'mimeType': mime, 'confidence': classification['confidence']})

    for tag in soup.find_all(['audio', 'video', 'source', 'track', 'iframe', 'img', 'a', 'link', 'script', 'embed', 'object']):
        name = tag.name
        if name in ('audio', 'video'):
            add(tag, tag.get('src'), name, name)
            if name == 'video':
                add(tag, tag.get('poster'), 'poster', 'image')
        elif name == 'source':
            parent = tag.find_parent(['audio', 'video', 'picture'])
            kind = 'image' if parent is not None and parent.name == 'picture' else parent.name if parent is not None else None
            add(tag, tag.get('src'), f'{kind or "media"}-source', kind)
            if kind == 'image':
                for candidate in srcset_urls(tag.get('srcset') or tag.get('data-srcset')):
                    add(tag, candidate, 'image-source', 'image')
        elif name == 'track':
            add(tag, tag.get('src'), str(tag.get('kind') or 'track'), 'transcript',
                label=tag.get('label'), language=tag.get('srclang'))
        elif name == 'iframe':
            src = tag.get('src') or tag.get('data-src')
            host = (urlparse(urljoin(page_url, str(src or ''))).hostname or '').lower()
            video = any(host == domain or host.endswith('.' + domain) for domain in
                        ('youtube.com', 'youtube-nocookie.com', 'youtu.be', 'vimeo.com', 'loom.com', 'wistia.com', 'wistia.net'))
            add(tag, src, 'embed', 'video' if video else 'other')
        elif name == 'img':
            add(tag, tag.get('src') or tag.get('data-src'), 'image', 'image')
            for candidate in srcset_urls(tag.get('srcset') or tag.get('data-srcset')):
                add(tag, candidate, 'image-source', 'image')
        elif name == 'a':
            attachment = tag.has_attr('download')
            add(tag, tag.get('href'), 'download' if attachment else 'link', 'document' if attachment else None)
        elif name == 'link':
            rel = tag.get('rel') or []
            rel = rel.split() if isinstance(rel, str) else rel
            declared = 'stylesheet' if 'stylesheet' in rel else 'image' if any('icon' in item for item in rel) else tag.get('as')
            add(tag, tag.get('href'), ' '.join(rel) or 'support', declared)
        elif name == 'script':
            add(tag, tag.get('src'), 'script', 'script')
        else:
            add(tag, tag.get('src') or tag.get('data'), 'embed', 'other')
    return resources


def fetch_asset(url: str, allow_url=None, timeout_sec: float = 15,
                max_bytes: int = 12 * 1024 * 1024, allowed_types=None) -> dict:
    """Retrieve a bounded public resource, validating each redirect and writing no files."""
    output = {'url': url, 'final_url': url, 'raw_bytes': b'', 'content_type': '',
              'content_disposition': '', 'status_code': None, 'error': None,
              'error_kind': None, 'sha256': None, 'redirect_chain': [],
              'resource_type': classify_resource(url)['type']}
    deadline = time.monotonic() + max(0.001, timeout_sec)
    current = url
    try:
        if max_bytes <= 0:
            output.update(error='Resource byte budget is exhausted.', error_kind='size-limit')
            return output
        for hop in range(6):
            if allow_url is not None and not allow_url(current):
                output.update(error='Resource refused by crawl policy.', error_kind='policy')
                return output
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Resource deadline reached.')
            with safe_requests_session(current) as session:
                response = session.get(current, headers={**DEFAULT_REQUEST_HEADERS, 'Accept': '*/*'},
                                       timeout=remaining, allow_redirects=False, stream=True)
                try:
                    output.update(final_url=current, status_code=response.status_code,
                                  content_type=response.headers.get('Content-Type', ''),
                                  content_disposition=response.headers.get('Content-Disposition', ''))
                    output['resource_type'] = classify_resource(current, output['content_type'], output['content_disposition'])['type']
                    if 300 <= response.status_code < 400 and response.headers.get('Location'):
                        output['redirect_chain'].append({'url': current, 'status_code': response.status_code})
                        if hop == 5:
                            raise ValueError('Resource redirect limit reached.')
                        current = urljoin(current, response.headers['Location'])
                        continue
                    if response.status_code != 200:
                        output.update(error=f'HTTP {response.status_code}', error_kind='http')
                        return output
                    if allowed_types is not None and output['resource_type'] not in allowed_types:
                        output.update(error='Resource type is reference-only under the download policy.', error_kind='reference-only')
                        return output
                    length = response.headers.get('Content-Length', '')
                    if length.isdigit() and int(length) > max_bytes:
                        output.update(error='Resource exceeds the byte limit.', error_kind='size-limit')
                        return output
                    chunks, size = [], 0
                    for chunk in response.iter_content(chunk_size=16384):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Resource deadline reached.')
                        size += len(chunk)
                        if size > max_bytes:
                            output.update(error='Resource exceeds the byte limit.', error_kind='size-limit')
                            return output
                        chunks.append(chunk)
                    raw = b''.join(chunks)
                    if not raw:
                        output.update(error='Resource response was empty.', error_kind='empty')
                        return output
                    output.update(raw_bytes=raw, sha256=hashlib.sha256(raw).hexdigest())
                    return output
                finally:
                    response.close()
        raise ValueError('Resource redirect limit reached.')
    except Exception as exc:
        output.update(error=str(exc), error_kind='timeout' if isinstance(exc, (TimeoutError, Timeout)) else 'fetch')
        return output
