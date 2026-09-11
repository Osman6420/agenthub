"""Consumer bearer-token authentication for the gateway.

Resolves ``Authorization: Bearer <token>`` to an active consumer. Returns a light
principal (not a Django user) so downstream permission/authorization is driven by
the consumer's bindings, never by Django auth flags.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import authentication, exceptions

from apps.identity.models import Consumer
from apps.identity.tokens import resolve_consumer
from apps.tenancy.context import set_tenant_context


class ConsumerPrincipal:
    """Minimal authenticated principal wrapping a resolved :class:`Consumer`."""

    def __init__(self, consumer: Consumer) -> None:
        self.consumer = consumer

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"consumer:{self.consumer.pk}"


class ConsumerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request: Any) -> tuple[ConsumerPrincipal, Consumer] | None:
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None  # no credentials -> DRF returns 401 via permission
        parts = header.split()
        if parts[0] != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid authorization header.")

        # Canonical durable API routes run outside the request-wide tenant
        # transaction. Authentication owns only this short token lookup scope;
        # admission and transitions install fresh transaction-local scopes.
        with transaction.atomic():
            consumer = resolve_consumer(parts[1])
            if consumer is None:
                raise exceptions.AuthenticationFailed("Invalid token.")
            set_tenant_context(consumer.organization_id)
        return ConsumerPrincipal(consumer), consumer

    def authenticate_header(self, request: Any) -> str:
        return self.keyword
