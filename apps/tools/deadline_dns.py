"""Bounded DNS work for short operator connection checks.

An OS lookup cannot be killed safely. Its slot remains occupied after the caller's
deadline until the resolver actually returns; waiting requests cannot accumulate.
"""

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import BoundedSemaphore

from apps.tools.egress import DnsResolver, EgressDenied, _default_resolver

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="connection-check-dns")
_SLOTS = BoundedSemaphore(4)


def bounded_resolver(deadline: float, resolver: DnsResolver | None = None) -> DnsResolver:
    def lookup(host: str, port: int):
        if time.monotonic() >= deadline:
            raise EgressDenied("DNS_DEADLINE_EXCEEDED")
        if not _SLOTS.acquire(blocking=False):
            raise EgressDenied("DNS_CAPACITY_EXCEEDED")

        def resolve():
            try:
                return (resolver or _default_resolver)(host, port)
            finally:
                _SLOTS.release()

        try:
            future = _POOL.submit(resolve)
        except RuntimeError:
            _SLOTS.release()
            raise EgressDenied("DNS_UNAVAILABLE") from None
        try:
            return future.result(timeout=max(0, deadline - time.monotonic()))
        except TimeoutError:
            raise EgressDenied("DNS_DEADLINE_EXCEEDED") from None

    return lookup
