"""Transaction-local PostgreSQL tenant scope (ADR-0004)."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import connection

MAX_TENANT_SCOPE_IDS = 2048


class TenantContextError(RuntimeError):
    pass


def normalize_tenant_scope(organization_ids: Iterable[int]) -> tuple[int, ...]:
    values: set[int] = set()
    for value in organization_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TenantContextError("TENANT_SCOPE_INVALID")
        values.add(value)
        if len(values) > MAX_TENANT_SCOPE_IDS:
            raise TenantContextError("TENANT_SCOPE_TOO_LARGE")
    return tuple(sorted(values))


def set_tenant_scope(organization_ids: Iterable[int]) -> tuple[int, ...]:
    """Set a bounded scope locally in the current transaction; never session-wide."""

    normalized = normalize_tenant_scope(organization_ids)
    if connection.vendor != "postgresql":
        return normalized
    if not connection.in_atomic_block:
        raise TenantContextError("TENANT_SCOPE_REQUIRES_TRANSACTION")
    value = ",".join(str(item) for item in normalized)
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [value])
    return normalized


def set_tenant_context(organization_id: int) -> None:
    """Compatibility helper for singleton worker/gateway scope."""

    set_tenant_scope((organization_id,))
