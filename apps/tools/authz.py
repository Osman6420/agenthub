"""Resolve verified human operators for tool-approval decisions."""

from __future__ import annotations

from django.contrib.auth import get_user_model


def resolve_actor(*, username: str):
    """Return one active authenticated user identity; authorization is target-scoped later."""
    return get_user_model().objects.filter(username=username, is_active=True).first()
