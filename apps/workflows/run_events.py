"""Safe, database-ordered event allocation for the unified Run aggregate."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.workflows.models import Run, RunEvent, RunEventType

MAX_EVENT_PAYLOAD_BYTES = 16 * 1024
MAX_EVENT_PAYLOAD_DEPTH = 8
_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "authorization",
        "body",
        "chain_of_thought",
        "chunk",
        "content",
        "credential",
        "document",
        "password",
        "prompt",
        "secret",
    }
)


def _is_forbidden_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
        return True
    return normalized == "token" or normalized.endswith("_token") or normalized.startswith("token_")


def _validate_payload_value(value: Any, *, depth: int) -> None:
    if depth > MAX_EVENT_PAYLOAD_DEPTH:
        raise ValidationError("run event payload exceeds maximum depth")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("run event payload numbers must be finite")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValidationError("run event payload keys must be strings")
            if _is_forbidden_key(key):
                raise ValidationError("run event payload contains a forbidden field")
            _validate_payload_value(child, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _validate_payload_value(child, depth=depth + 1)
        return
    raise ValidationError("run event payload must contain only JSON values")


def validate_run_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValidationError("run event payload must be an object")
    normalized = dict(payload)
    _validate_payload_value(normalized, depth=1)
    encoded = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(encoded) > MAX_EVENT_PAYLOAD_BYTES:
        raise ValidationError("run event payload exceeds 16 KiB")
    return normalized


def append_locked_run_event(
    *,
    run: Run,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    node_id: str = "",
    outcome: str = "",
    reason_code: str = "",
    state_checksum: str = "",
) -> RunEvent:
    """Append to a Run already locked by the current transaction."""

    if event_type not in RunEventType.values:
        raise ValidationError("unsupported run event type")
    safe_payload = validate_run_event_payload(payload or {})
    sequence = run.next_event_sequence
    event = RunEvent.objects.create(
        organization=run.organization,
        run=run,
        sequence=sequence,
        event_type=event_type,
        payload=safe_payload,
        node_id=node_id,
        outcome=outcome,
        reason_code=reason_code,
        state_checksum=state_checksum,
    )
    run.next_event_sequence = sequence + 1
    return event


@transaction.atomic
def append_run_event(
    *,
    run_id: uuid.UUID,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    node_id: str = "",
    outcome: str = "",
    reason_code: str = "",
    state_checksum: str = "",
) -> RunEvent:
    """Allocate the next sequence while holding the canonical Run row lock."""

    run = Run.objects.select_for_update().get(pk=run_id)
    event = append_locked_run_event(
        run=run,
        event_type=event_type,
        payload=payload,
        node_id=node_id,
        outcome=outcome,
        reason_code=reason_code,
        state_checksum=state_checksum,
    )
    run.save(update_fields=["next_event_sequence", "updated_at"])
    return event
