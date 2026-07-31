from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.tools.authz import resolve_actor

pytestmark = pytest.mark.django_db


def _user(username: str, *, superuser: bool = False):
    return get_user_model().objects.create_user(
        username=username,
        password=None,
        is_superuser=superuser,
        is_staff=superuser,
    )


def test_resolve_actor_returns_active_human_identity_without_inventing_roles() -> None:
    daily_admin = _user("daily-admin")
    recovery = _user("recovery", superuser=True)

    assert resolve_actor(username=daily_admin.get_username()) == daily_admin
    assert resolve_actor(username=recovery.get_username()) == recovery


def test_resolve_actor_is_non_enumerating_for_unknown_or_inactive_actor() -> None:
    inactive = _user("inactive")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])

    assert resolve_actor(username="missing") is None
    assert resolve_actor(username=inactive.get_username()) is None
