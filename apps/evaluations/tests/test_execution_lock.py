"""Concurrent delivery cannot execute the same evaluation across commit boundaries."""

from uuid import uuid4

import pytest
from django.db import connection

from apps.evaluations.execution_lock import question_evaluation_lock, release_evaluation_lock


@pytest.mark.django_db(transaction=True)
def test_question_evaluation_lock_spans_commits_and_releases_on_failure():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL session ownership")
    run_id = uuid4().int % 2_000_000_000
    name = f"agenthub:question-evaluation:1:{run_id}"
    probe = connection.copy(alias="evaluation-lock-probe")
    try:
        with pytest.raises(RuntimeError, match="worker failure"):
            with question_evaluation_lock(1, run_id) as acquired:
                assert acquired
                connection.commit()
                with probe.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [name])
                    assert cursor.fetchone()[0] is False
                raise RuntimeError("worker failure")
        with probe.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [name])
            assert cursor.fetchone()[0] is True
        with question_evaluation_lock(1, run_id) as acquired:
            assert not acquired
        # Same numeric run in another tenant has a distinct ownership key.
        with question_evaluation_lock(2, run_id) as acquired:
            assert acquired
    finally:
        probe.close()


@pytest.mark.parametrize(
    "lock, prefix",
    [
        (question_evaluation_lock, "QUESTION"),
        (release_evaluation_lock, "RELEASE"),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_reconnected_evaluation_owner_cannot_continue_database_work(lock, prefix):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL connection replacement fencing")
    with lock(1, uuid4().int % 2_000_000_000) as acquired:
        assert acquired
        connection.close()
        with pytest.raises(RuntimeError, match=f"{prefix}_EVALUATION_OWNER_LOST"):
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
