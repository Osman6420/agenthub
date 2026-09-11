"""Per-consumer rate throttle, tested in isolation to avoid cache contamination."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.gateway.throttling import ConsumerRateThrottle
from apps.identity.models import Consumer
from apps.tenancy.models import Organization


class _Req:
    def __init__(self, auth: object) -> None:
        self.auth = auth


@pytest.mark.django_db
def test_throttle_blocks_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    org = Organization.objects.create(slug="o", name="O")
    consumer = Consumer.objects.create(organization=org, subject="s", name="C", protocol="rest")

    throttle = ConsumerRateThrottle()
    # Force a small rate deterministically.
    monkeypatch.setattr(throttle, "rate", "2/min")
    throttle.num_requests, throttle.duration = throttle.parse_rate("2/min")

    request = _Req(consumer)
    assert throttle.allow_request(request, view=None) is True
    assert throttle.allow_request(request, view=None) is True
    assert throttle.allow_request(request, view=None) is False  # third exceeds 2/min


@pytest.mark.django_db
def test_throttle_ignores_unauthenticated() -> None:
    throttle = ConsumerRateThrottle()
    assert throttle.get_cache_key(_Req(None), view=None) is None
