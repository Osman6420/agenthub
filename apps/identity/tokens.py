"""Consumer bearer-token generation and resolution.

Tokens are random, shown once, and stored only as SHA-256 hashes. Resolution is
fail-closed: a token resolves to a consumer only when both the token and the
consumer are active.
"""

from __future__ import annotations

import hashlib
import secrets

from django.utils import timezone

from apps.identity.models import Consumer, ConsumerStatus, ConsumerToken, TokenStatus

_TOKEN_BYTES = 32
_PREFIX_LEN = 8


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_token(consumer: Consumer, name: str) -> tuple[ConsumerToken, str]:
    """Create a token for a consumer; returns (record, plaintext-shown-once)."""
    raw = secrets.token_urlsafe(_TOKEN_BYTES)
    token = ConsumerToken.objects.create(
        consumer=consumer,
        name=name,
        prefix=raw[:_PREFIX_LEN],
        token_hash=hash_token(raw),
    )
    return token, raw


def resolve_consumer(raw_token: str) -> Consumer | None:
    """Resolve an active consumer from a bearer token, or None."""
    if not raw_token:
        return None
    token = (
        ConsumerToken.objects.select_related("consumer")
        .filter(token_hash=hash_token(raw_token), status=TokenStatus.ACTIVE)
        .first()
    )
    if token is None or token.consumer.status != ConsumerStatus.ACTIVE:
        return None
    # Best-effort last-used stamp; never blocks the request path.
    ConsumerToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.consumer
