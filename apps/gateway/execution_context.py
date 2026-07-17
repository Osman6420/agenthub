"""Signed, short-lived ExecutionContext (v3 plan §10.3).

The gateway issues a context after a request is authenticated and authorized. It is
HMAC-signed with the Django secret and carries an expiry. Downstream runtime code
verifies signature + expiry before acting (fail-closed).
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.artifacts.validation import canonical_json


class ExecutionContextInvalid(ValueError):
    """Raised when an ExecutionContext fails signature or expiry verification."""


def _sign(payload: dict[str, Any]) -> str:
    message = canonical_json(payload).encode("utf-8")
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, message, sha256).hexdigest()


def issue_execution_context(
    *,
    organization_id: int,
    project_id: int,
    scenario_id: int,
    scenario_alias: str,
    consumer_id: int,
    capabilities: list[str],
    release_id: int,
    request_id: str,
    allowed_tool_ids: list[int] | None = None,
    ttl_seconds: int | None = None,
    composition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = timezone.now()
    ttl = ttl_seconds if ttl_seconds is not None else settings.EXECUTION_CONTEXT_TTL_SECONDS
    payload = {
        "organization_id": organization_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
        "scenario_alias": scenario_alias,
        "consumer_id": consumer_id,
        "capabilities": sorted(capabilities),
        "allowed_tool_ids": sorted(allowed_tool_ids or []),
        "release_id": release_id,
        "request_id": request_id,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
    }
    if composition is not None:
        # Server-owned attenuated child lineage/budget claim (P2.6.5). Only present for a child
        # run's fresh context; it is part of the signed payload so it cannot be forged or copied
        # from the parent. It is never authorization by itself — the child boundary re-authorizes.
        payload["composition"] = composition
    return {**payload, "signature": _sign(payload)}


def verify_execution_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return the verified payload or raise :class:`ExecutionContextInvalid`."""
    if not isinstance(context, dict) or "signature" not in context:
        raise ExecutionContextInvalid("missing signature")
    payload = {k: v for k, v in context.items() if k != "signature"}
    expected = _sign(payload)
    if not hmac.compare_digest(str(context["signature"]), expected):
        raise ExecutionContextInvalid("bad signature")

    expires_at = payload.get("expires_at")
    if not expires_at:
        raise ExecutionContextInvalid("missing expiry")
    if timezone.now() > datetime.fromisoformat(expires_at):
        raise ExecutionContextInvalid("expired")
    return payload
