"""Per-consumer rate limiting.

Keyed by the resolved consumer id so limits are per caller, not per IP. The default
rate is generous (settings ``consumer`` scope); tune per environment. Limiting fails
open (never blocks on a cache outage) — authentication/authorization never do.
"""

from __future__ import annotations

from typing import Any

from rest_framework.throttling import SimpleRateThrottle

from apps.identity.models import Consumer


class ConsumerRateThrottle(SimpleRateThrottle):
    scope = "consumer"

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        consumer = getattr(request, "auth", None)
        if not isinstance(consumer, Consumer):
            return None  # unauthenticated requests are handled by permissions
        return self.cache_format % {"scope": self.scope, "ident": consumer.pk}
