"""Consumer token creation and fail-closed resolution."""

from __future__ import annotations

import pytest

from apps.identity.models import Consumer, ConsumerStatus, TokenStatus
from apps.identity.tokens import create_token, hash_token, resolve_consumer
from apps.tenancy.models import Organization


def _consumer(status: str = ConsumerStatus.ACTIVE) -> Consumer:
    org = Organization.objects.create(slug="o", name="O")
    return Consumer.objects.create(
        organization=org, subject="svc", name="C", protocol="rest", status=status
    )


@pytest.mark.django_db
def test_token_is_stored_hashed_and_resolves() -> None:
    consumer = _consumer()
    token, raw = create_token(consumer, "t")
    assert token.token_hash == hash_token(raw)
    assert token.token_hash != raw  # plaintext is never stored
    assert resolve_consumer(raw) == consumer


@pytest.mark.django_db
def test_unknown_token_resolves_to_none() -> None:
    _consumer()
    assert resolve_consumer("nope") is None
    assert resolve_consumer("") is None


@pytest.mark.django_db
def test_revoked_token_denied() -> None:
    consumer = _consumer()
    token, raw = create_token(consumer, "t")
    token.status = TokenStatus.REVOKED
    token.save(update_fields=["status"])
    assert resolve_consumer(raw) is None


@pytest.mark.django_db
def test_disabled_consumer_denied() -> None:
    consumer = _consumer(status=ConsumerStatus.DISABLED)
    _, raw = create_token(consumer, "t")
    assert resolve_consumer(raw) is None
