"""Shared authorization for release-lifecycle entry points (console + CLI).

Lifecycle mutations (eval, promote, canary, rollback) require the `release_manager`
role in the release's organization, or platform admin. CLI actors are resolved to a
real Django user before the check — a username string is never trusted on its own.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser

from apps.tenancy.services import can_manage_releases


class ReleaseAuthorizationError(PermissionError):
    """Raised when an actor may not perform a release-lifecycle action. ``code`` is stable."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def resolve_release_manager(*, username: str, organization_id: int) -> AbstractBaseUser:
    """Resolve ``username`` to a user and require release-management rights in the org."""
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        raise ReleaseAuthorizationError("UNKNOWN_ACTOR")
    if not can_manage_releases(user, organization_id):
        raise ReleaseAuthorizationError("NOT_RELEASE_MANAGER")
    return user
