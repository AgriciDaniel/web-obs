"""Spawned fetch workers with shared request leases and owned-process deadlines."""
from __future__ import annotations

from collections import deque
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager
import multiprocessing as mp
from multiprocessing.managers import BaseManager
import os
import queue
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlparse
import uuid

from url_safety import request_context

CAPACITIES = {'page-http': 3, 'render': 1, 'asset': 2, 'link': 3}


class WorkerError(RuntimeError):
    pass


class TaskDeadlineExceeded(TimeoutError):
    pass


def origin_key(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)
    return f'{parsed.scheme.lower()}://{host}' + (f':{port}' if port != (443 if parsed.scheme.lower() == 'https' else 80) else '')


class _LeaseBroker:
    """Server-owned critical sections survive a worker dying during its RPC."""
    def __init__(self, maximum, per_origin, interval):
        self.maximum, self.per_origin, self.interval = maximum, per_origin, interval
        self.lock = threading.Lock()
        self.leases, self.next_start = {}, {}
        self.peak, self.origin_peaks = 0, {}

    def try_acquire(self, owner, url):
        origin = origin_key(url)
        with self.lock:
            count = sum(row[1] == origin for row in self.leases.values())
            now = time.monotonic()
            if len(self.leases) >= self.maximum or count >= self.per_origin or now < self.next_start.get(origin, 0):
                return None
            token = uuid.uuid4().hex
            self.leases[token] = (owner, origin)
            self.next_start[origin] = now + self.interval
            self.peak = max(self.peak, len(self.leases))
            self.origin_peaks[origin] = max(self.origin_peaks.get(origin, 0), count + 1)
            return token

    def release(self, token):
        with self.lock:
            self.leases.pop(token, None)

    def recover(self, owner):
        with self.lock:
            tokens = [token for token, row in self.leases.items() if row[0] == owner]
            for token in tokens:
                del self.leases[token]
            return len(tokens)

    def snapshot(self):
        with self.lock:
            return {'active': len(self.leases), 'peak': self.peak,
                    'origins': dict(self.origin_peaks), 'leases': list(self.leases.values())}


class _BrokerManager(BaseManager):
    pass


_BrokerManager.register('LeaseBroker', _LeaseBroker)


def _policies(payload):
    import hashlib
    from site_intel import build_robots_policy, robots_url_decision
    from sitemap import MAX_ROBOTS_BYTES, _bounded_fetch_bytes, is_same_site_host
    from url_safety import request_policy_override
    policies = dict(payload.get('robots_policies', payload.get('policies', {})))
    observed, receipts = {}, {}
    primary_host = payload.get('target_host') or urlparse(payload['url']).hostname

    def policy_for(url):
        key = origin_key(url)
        if key not in policies:
            if len(observed) >= 16:
                return build_robots_policy('', None, error='New-origin robots policy budget reached.')
            robots_url = key + '/robots.txt'
            # This is the explicit robots bootstrap request, not a page-policy
            # exemption. Safety, shared leases and the task deadline still apply.
            with request_policy_override(lambda _target: True):
                fetched = _bounded_fetch_bytes(robots_url, MAX_ROBOTS_BYTES)
            policy = build_robots_policy(fetched['content'].decode('utf-8', errors='replace'),
                fetched['status_code'], fetched['error'], fetched['too_large'])
            policies[key] = observed[key] = policy
            receipts[key] = {'url': robots_url, 'final_url': fetched['final_url'],
                'status_code': fetched['status_code'], 'content_type': fetched['content_type'],
                'error': fetched['error'], 'too_large': fetched['too_large'],
                'raw_bytes': fetched['content'],
                'sha256': hashlib.sha256(fetched['content']).hexdigest(),
                'raw_kind': 'http-response-decoded'}
        return policies[key]

    def page(url):
        if not is_same_site_host(urlparse(url).hostname or '', primary_host or ''):
            return False
        return robots_url_decision(policy_for(url), url)['allowed']
    def resource(url):
        key = origin_key(url)
        if key in policies:
            return robots_url_decision(policies[key], url)['allowed']
        if is_same_site_host(urlparse(url).hostname or '', primary_host or ''):
            return robots_url_decision(policy_for(url), url)['allowed']
        # Only foreign static resources can use this explicit policy exception.
        return payload.get('allow_foreign_resources', True) and not is_same_site_host(urlparse(url).hostname or '', primary_host or '')
    page.observed_policies = observed
    page.policy_receipts = receipts
    return page, resource


def _worker_main(connection, limiter):
    if os.name == 'posix':
        os.setsid()
    from page_fetch import PageFetcher
    fetcher = PageFetcher()
    try:
        while True:
            job = connection.recv()
            if job is None:
                break
            identifier, operation, payload, deadline = job
            try:
                page_policy, resource_policy = _policies(payload)
                transport_policy = page_policy if operation == 'page-http' else resource_policy
                with request_context(limiter, identifier, deadline, allow_url=transport_policy):
                    remaining = max(.001, deadline - time.monotonic())
                    if operation in ('page-http', 'render'):
                        result = fetcher.fetch(payload['url'],
                            render_mode='never' if operation == 'page-http' else 'always',
                            timeout_sec=remaining, allow_url=page_policy,
                            allow_resource_url=resource_policy, prior_http=payload.get('prior_http'))
                    elif operation == 'asset':
                        from resources import fetch_asset
                        result = fetch_asset(payload['url'], allow_url=resource_policy,
                            timeout_sec=remaining, max_bytes=payload.get('max_bytes', 12 * 1024 * 1024),
                            allowed_types=payload.get('allowed_types'))
                    elif operation == 'link':
                        from site_intel import _check_direct_external_url
                        result = _check_direct_external_url(payload['url'], deadline,
                            payload.get('request_timeout', 3))
                    else:
                        raise ValueError('Unsupported worker operation.')
                if page_policy.observed_policies:
                    result['discovered_robots_policies'] = page_policy.observed_policies
                    result['robots_receipts'] = page_policy.policy_receipts
                connection.send((identifier, True, result))
            except Exception as exc:
                connection.send((identifier, False, type(exc).__name__ + ': ' + str(exc)))
            finally:
                limiter.recover(identifier)
    except (EOFError, BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        try:
            fetcher.close()
        finally:
            connection.close()


def _process_tree(root_pid):
    """Read only this owned tree and retain birth times against PID recycling."""
    if not Path('/proc').is_dir():
        return {}
    pending, owned = [root_pid], {}
    while pending:
        pid = pending.pop()
        if pid in owned:
            continue
        directory = Path(f'/proc/{pid}')
        try:
            fields = (directory / 'stat').read_text(encoding='utf-8').rsplit(')', 1)[1].split()
            owned[pid] = int(fields[19])
            for task in (directory / 'task').iterdir():
                try:
                    pending.extend(int(child) for child in (task / 'children').read_text(encoding='utf-8').split())
                except (OSError, ValueError):
                    pass
        except (OSError, ValueError, IndexError):
            continue
    return owned


def _same_process(pid, started):
    try:
        return int(Path(f'/proc/{pid}/stat').read_text(encoding='utf-8').rsplit(')', 1)[1].split()[19]) == started
    except (OSError, ValueError, IndexError):
        return False


def _stop_owned(process, known=None):
    if process is None:
        return
    owned = dict(known or {})
    if process.is_alive():
        owned.update(_process_tree(process.pid))
    if process.is_alive() or owned:
        if os.name == 'nt':
            import subprocess
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=3, check=False)
        else:
            # Browser launchers can create their own process group. Kill each
            # verified owned group as well as individual descendants.
            for pid, started in sorted(owned.items(), reverse=True):
                if not _same_process(pid, started):
                    continue
                try:
                    if os.getpgid(pid) == pid:
                        os.killpg(pid, signal.SIGKILL)
                    else:
                        os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.is_alive():
                process.kill()
    process.join(timeout=.2)
    # SIGKILL delivery and descendant exit are asynchronous. Confirm exit before
    # reporting the task finished, within a bounded cleanup grace period.
    cleanup_end = time.monotonic() + .5
    while time.monotonic() < cleanup_end:
        running = []
        for pid, started in owned.items():
            if not _same_process(pid, started):
                continue
            try:
                state = Path(f'/proc/{pid}/stat').read_text(encoding='utf-8').rsplit(')', 1)[1].split()[0]
                if state != 'Z':
                    running.append(pid)
            except (OSError, IndexError):
                pass
        if not running:
            break
        time.sleep(.005)
    if running:
        raise WorkerError('Owned process cleanup could not be confirmed within its grace period.')


class WorkerDispatcher:
    def __init__(self, max_inflight=6, per_origin=2, min_interval_sec=.15, max_pending=256):
        self.maximum = max(1, min(6, int(max_inflight)))
        self.max_pending = max_pending
        self.context = mp.get_context('spawn')
        self.manager = _BrokerManager(ctx=self.context)
        self.manager.start()
        self.limiter = self.manager.LeaseBroker(self.maximum, max(1, min(2, int(per_origin))), max(0, min_interval_sec))
        self.lock = threading.RLock()
        self.pending, self.slots = deque(), []
        self.quarantined = []
        self.failure = None
        self.closed = False
        self.wake = threading.Event()
        self.supervisor = threading.Thread(target=self._supervise, name='web-obs-worker-supervisor', daemon=True)
        self.supervisor.start()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def submit(self, operation, payload, timeout_sec=25):
        if operation not in CAPACITIES:
            raise ValueError('Unknown worker operation: ' + str(operation))
        if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
            raise ValueError('Worker payload must contain a URL.')
        future = Future()
        with self.lock:
            if self.closed:
                raise RuntimeError('Worker dispatcher is closed.')
            if self.failure:
                raise WorkerError(str(self.failure))
            if len(self.pending) >= self.max_pending:
                raise WorkerError('Worker pending queue limit reached.')
            self.pending.append({'id': uuid.uuid4().hex, 'operation': operation,
                'payload': dict(payload), 'timeout': max(.01, float(timeout_sec)), 'future': future})
        self.wake.set()
        return future

    def _start_slot(self, operation):
        parent = child = process = slot = None
        commands, results = queue.Queue(), queue.Queue()
        try:
            parent, child = self.context.Pipe()
            process = self.context.Process(target=_worker_main, args=(child, self.limiter), daemon=False)
            process.start()
            child.close()
            slot = {'operation': operation, 'process': process, 'pipe': parent, 'job': None,
                    'commands': commands, 'results': results, 'owned': _process_tree(process.pid), 'next_tree_check': 0}
            def receive():
                try:
                    while True:
                        results.put(parent.recv())
                        self.wake.set()
                except (EOFError, OSError) as exc:
                    results.put(('__closed__', False, str(exc)))
                    self.wake.set()
            def send():
                try:
                    while True:
                        command = commands.get()
                        parent.send(command)
                        if command is None:
                            return
                except (EOFError, OSError):
                    pass
            threading.Thread(target=receive, daemon=True, name='web-obs-result-reader').start()
            threading.Thread(target=send, daemon=True, name='web-obs-task-writer').start()
            self.slots.append(slot)
            return slot
        except Exception:
            # Startup can fail after pipes or a live process already exist.
            # Nothing has been handed a task yet, but each partial resource is ours.
            try:
                if process is not None and process.pid is not None:
                    try:
                        _stop_owned(process, slot.get('owned') if slot else None)
                        process.close()
                    except WorkerError as exc:
                        self.failure = exc
                        self.quarantined.append(slot or {'operation': operation,
                            'process': process, 'pipe': parent, 'job': None,
                            'commands': commands, 'results': results,
                            'owned': _process_tree(process.pid), 'next_tree_check': 0})
            finally:
                commands.put(None)
                if child is not None:
                    child.close()
                if parent is not None:
                    parent.close()
            raise

    def _discard(self, slot):
        job = slot['job']
        issue = None
        try:
            _stop_owned(slot['process'], slot.get('owned'))
        except WorkerError as exc:
            issue = self.failure = exc
            self.quarantined.append(slot)
        finally:
            if job and issue is None:
                self.limiter.recover(job['id'])
            slot['commands'].put(None)
            slot['pipe'].close()
            self.slots.remove(slot)
        return issue

    def _supervise(self):
        while True:
            with self.lock:
                if self.closed:
                    return
                now = time.monotonic()
                for slot in list(self.slots):
                    job = slot['job']
                    if slot['operation'] == 'render' and now >= slot['next_tree_check']:
                        slot['owned'].update(_process_tree(slot['process'].pid))
                        slot['next_tree_check'] = now + .1
                    if job is None:
                        if not slot['process'].is_alive():
                            self._discard(slot)
                        continue
                    future = job['future']
                    if now >= job['deadline']:
                        issue = self._discard(slot)
                        future.set_exception(issue or TaskDeadlineExceeded('Worker task exceeded its absolute deadline.'))
                    elif not slot['results'].empty():
                        try:
                            identifier, success, result = slot['results'].get_nowait()
                            if identifier != job['id']:
                                raise WorkerError('Worker returned a mismatched task ID.')
                            slot['job'] = None
                            self.limiter.recover(job['id'])
                            if success:
                                future.set_result(result)
                            else:
                                future.set_exception(WorkerError(result))
                        except (EOFError, OSError, WorkerError) as exc:
                            issue = self._discard(slot)
                            future.set_exception(issue or WorkerError('Worker exited before returning its result.'))
                    elif not slot['process'].is_alive():
                        issue = self._discard(slot)
                        future.set_exception(issue or WorkerError('Worker exited unexpectedly.'))
                if self.failure:
                    for job in self.pending:
                        if not job['future'].done():
                            job['future'].set_exception(WorkerError(str(self.failure)))
                    self.pending.clear()
                    for slot in list(self.slots):
                        job = slot['job']
                        if job:
                            self._discard(slot)
                            job['future'].set_exception(WorkerError(str(self.failure)))
                active = self.maximum if self.failure else sum(slot['job'] is not None for slot in self.slots)
                # Scan all pending jobs so a busy render lane cannot stall HTTP.
                for job in list(self.pending):
                    if job['future'].cancelled():
                        self.pending.remove(job)
                        continue
                    if active >= self.maximum:
                        break
                    operation = job['operation']
                    slot = next((s for s in self.slots if s['operation'] == operation and s['job'] is None), None)
                    if slot is None and sum(s['operation'] == operation for s in self.slots) < CAPACITIES[operation]:
                        try:
                            slot = self._start_slot(operation)
                        except Exception as exc:
                            self.pending.remove(job)
                            if job['future'].set_running_or_notify_cancel():
                                job['future'].set_exception(WorkerError(
                                    f"Could not start {operation} worker: {type(exc).__name__}: {exc}"))
                            if self.failure:
                                break
                            continue
                    if slot is None:
                        continue
                    self.pending.remove(job)
                    if not job['future'].set_running_or_notify_cancel():
                        continue
                    job['deadline'] = time.monotonic() + job['timeout']
                    slot['job'] = job
                    try:
                        slot['commands'].put((job['id'], operation, job['payload'], job['deadline']))
                        active += 1
                    except (OSError, EOFError) as exc:
                        issue = self._discard(slot)
                        job['future'].set_exception(issue or WorkerError(str(exc)))
            self.wake.wait(.01)
            self.wake.clear()

    def cancel_all(self):
        with self.lock:
            for job in self.pending:
                job['future'].cancel()
            self.pending.clear()
            for slot in list(self.slots):
                job = slot['job']
                if job is not None:
                    issue = self._discard(slot)
                    if not job['future'].done():
                        job['future'].set_exception(issue or CancelledError('Capture cancelled.'))
        self.wake.set()

    @contextmanager
    def parent_requests(self, timeout_sec=None):
        owner = 'parent-' + uuid.uuid4().hex
        deadline = time.monotonic() + timeout_sec if timeout_sec is not None else None
        try:
            with request_context(self.limiter, owner, deadline):
                yield
        finally:
            self.limiter.recover(owner)

    def stats(self):
        with self.lock:
            return {**self.limiter.snapshot(), 'workerPids': [s['process'].pid for s in self.slots],
                    'pending': len(self.pending), 'running': sum(s['job'] is not None for s in self.slots),
                    'cleanupPending': len(self.quarantined)}

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.cancel_all()
            self.closed = True
            slots = list(self.slots) + self.quarantined
        self.wake.set()
        self.supervisor.join(timeout=2)
        cleanup_error = None
        for slot in slots:
            try:
                slot['commands'].put(None)
                slot['process'].join(timeout=1)
            except (OSError, EOFError):
                pass
            finally:
                try:
                    _stop_owned(slot['process'], slot.get('owned'))
                except WorkerError as exc:
                    cleanup_error = exc
                slot['pipe'].close()
        self.slots.clear()
        self.manager.shutdown()
        if cleanup_error:
            raise cleanup_error
