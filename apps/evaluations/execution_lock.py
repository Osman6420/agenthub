"""Keep one question evaluation owner across independently committed cases."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from django.db import connection


@contextmanager
def question_evaluation_lock(organization_id: int, run_id: int) -> Iterator[bool]:
    with _evaluation_lock("question", organization_id, run_id) as acquired:
        yield acquired


@contextmanager
def release_evaluation_lock(organization_id: int, run_id: int) -> Iterator[bool]:
    with _evaluation_lock("release", organization_id, run_id) as acquired:
        yield acquired


@contextmanager
def _evaluation_lock(kind: str, organization_id: int, run_id: int) -> Iterator[bool]:
    # Same session-lock topology as ingestion.source_lock. Tenant scope remains
    # transaction-local; this lock conveys no data access or authorization.
    if connection.vendor != "postgresql":
        yield True
        return
    name = f"agenthub:{kind}-evaluation:{organization_id}:{run_id}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [name])
        acquired = bool(cursor.fetchone()[0])
    owner_session = connection.connection

    def require_owner_session(
        execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any
    ) -> Any:
        # Reconnecting loses a session advisory lock. Never record another case
        # or issue later node I/O as though the replacement connection still owns it.
        if connection.connection is not owner_session:
            raise RuntimeError(f"{kind.upper()}_EVALUATION_OWNER_LOST")
        return execute(sql, params, many, context)

    try:
        if acquired:
            with connection.execute_wrapper(require_owner_session):
                yield True
        else:
            yield False
    finally:
        if acquired and connection.connection is owner_session:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [name])
