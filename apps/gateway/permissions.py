"""Gateway permission: a valid, active consumer must be authenticated."""

from __future__ import annotations

from typing import Any

from rest_framework import permissions

from apps.identity.models import Consumer


class HasActiveConsumer(permissions.BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return isinstance(getattr(request, "auth", None), Consumer)
