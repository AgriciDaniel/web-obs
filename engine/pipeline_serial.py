"""Synchronous dispatcher for deterministic pipeline regression comparisons."""
from concurrent.futures import Future
from contextlib import nullcontext
import time
import uuid

from page_fetch import PageFetcher
from url_safety import request_context
from workers import CAPACITIES, WorkerError, _LeaseBroker, _policies


class SerialDispatcher:
    """Run the same operations and request policies without overlapping tasks.

    This benchmark mode has cooperative request deadlines. The production
    dispatcher additionally enforces process deadlines and cancellation.
    """
    def __init__(self, max_inflight=6, per_origin=2, min_interval_sec=.15,
                 max_pending=256):
        self.fetcher = PageFetcher()
        self.limiter = _LeaseBroker(1, 1, max(0, min_interval_sec))
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def submit(self, operation, payload, timeout_sec=25):
        if operation not in CAPACITIES:
            raise ValueError('Unknown worker operation: ' + str(operation))
        if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
            raise ValueError('Worker payload must contain a URL.')
        if self.closed:
            raise RuntimeError('Worker dispatcher is closed.')
        future = Future()
        future.set_running_or_notify_cancel()
        owner = uuid.uuid4().hex
        deadline = time.monotonic() + max(.01, float(timeout_sec))
        try:
            page_policy, resource_policy = _policies(payload)
            with request_context(self.limiter, owner, deadline, allow_url=page_policy if operation == 'page-http' else resource_policy):
                remaining = max(.001, deadline - time.monotonic())
                if operation in ('page-http', 'render'):
                    result = self.fetcher.fetch(payload['url'],
                        render_mode='never' if operation == 'page-http' else 'always',
                        timeout_sec=remaining, allow_url=page_policy,
                        allow_resource_url=resource_policy,
                        prior_http=payload.get('prior_http'))
                elif operation == 'asset':
                    from resources import fetch_asset
                    result = fetch_asset(payload['url'], allow_url=resource_policy,
                        timeout_sec=remaining,
                        max_bytes=payload.get('max_bytes', 12 * 1024 * 1024),
                        allowed_types=payload.get('allowed_types'))
                else:
                    from site_intel import _check_direct_external_url
                    result = _check_direct_external_url(payload['url'], deadline,
                        payload.get('request_timeout', 3))
            result['discovered_robots_policies'] = dict(page_policy.observed_policies)
            result['robots_receipts'] = dict(page_policy.policy_receipts)
            future.set_result(result)
        except Exception as exc:
            future.set_exception(WorkerError(type(exc).__name__ + ': ' + str(exc)))
        finally:
            self.limiter.recover(owner)
        return future

    def parent_requests(self, timeout_sec=None):
        return nullcontext()

    def cancel_all(self):
        # submit returns only after the current task finishes; no queue remains.
        return None

    def stats(self):
        return {**self.limiter.snapshot(), 'workerPids': [], 'pending': 0, 'running': 0}

    def close(self):
        if not self.closed:
            self.closed = True
            self.fetcher.close()
