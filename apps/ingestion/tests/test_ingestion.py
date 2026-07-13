from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.audit.models import AuditEvent
from apps.ingestion.connectors import (
    CONNECTORS,
    ConfluenceConnector,
    ConnectorError,
    RawDocument,
    S3Connector,
    _validate_https_url,
)
from apps.ingestion.models import Chunk, IndexStatus, RunStatus, Source
from apps.ingestion.services import claim_run, create_run, execute_run, source_lock
from apps.tenancy.models import Organization


class FakeConnector:
    def fetch(self, source: Source) -> list[RawDocument]:
        return [RawDocument(uri="https://docs.example/policy", content=b"Returns are allowed.")]


@pytest.fixture
def source(db: Any) -> Source:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    return Source.objects.create(
        organization=organization,
        slug="policies",
        name="Policies",
        connector_type="https",
        connector_config={"url": "https://docs.example/policy"},
    )


@pytest.mark.django_db
def test_run_claim_is_single_winner(source: Source) -> None:
    run = create_run(source=source)

    assert claim_run(run.pk) is not None
    assert claim_run(run.pk) is None


@pytest.mark.django_db
def test_success_creates_promotable_index_and_audit(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(CONNECTORS, "https", FakeConnector)
    run = create_run(source=source)

    assert execute_run(run.pk) == RunStatus.SUCCEEDED

    run.refresh_from_db()
    assert run.index_version is not None
    assert run.index_version.status == IndexStatus.PROMOTABLE
    assert run.index_version.document_count == 1
    assert run.index_version.chunk_count == 1
    assert (
        Chunk.objects.filter(
            organization=source.organization, index_version=run.index_version
        ).count()
        == 1
    )
    assert AuditEvent.objects.filter(action="ingestion.succeeded", resource_id=str(run.pk)).exists()


@pytest.mark.django_db
def test_terminal_failure_dead_letters_and_audits(source: Source) -> None:
    source.parser = "unknown"
    source.save(update_fields=["parser"])
    run = create_run(source=source, max_attempts=1)

    assert execute_run(run.pk) == RunStatus.DEAD_LETTER

    run.refresh_from_db()
    assert run.error_code == "PIPELINE_UNSUPPORTED"
    event = AuditEvent.objects.get(action="ingestion.dead_letter", resource_id=str(run.pk))
    assert event.reason == "PIPELINE_UNSUPPORTED"
    assert "url" not in (event.after or {})


@pytest.mark.django_db
def test_source_rejects_inline_credentials(source: Source) -> None:
    source.connector_config = {"url": "https://docs.example/x", "token": "secret"}
    with pytest.raises(ValidationError, match="inline credentials"):
        source.full_clean()


def test_https_connector_denies_unallowlisted_host(settings: Any) -> None:
    settings.INGESTION_HTTP_ALLOWED_HOSTS = []
    with pytest.raises(ConnectorError, match="HOST_DENIED"):
        _validate_https_url("https://localhost/internal")


def test_https_connector_denies_non_https(settings: Any) -> None:
    settings.INGESTION_HTTP_ALLOWED_HOSTS = ["docs.example"]
    with pytest.raises(ConnectorError, match="URL_DENIED"):
        _validate_https_url("http://docs.example/policy")


def test_s3_connector_denies_cross_tenant_key(source: Source, settings: Any) -> None:
    settings.OBJECT_STORE["bucket"] = "agenthub"
    source.connector_type = "s3"
    source.connector_config = {"bucket": "agenthub", "key": "other-org/private.txt"}
    with pytest.raises(ConnectorError, match="OBJECT_KEY_DENIED"):
        S3Connector().fetch(source)


def test_confluence_source_cannot_use_legacy_one_shot_pipeline(source: Source) -> None:
    with pytest.raises(ConnectorError, match="CONFLUENCE_SYNC_REQUIRED"):
        ConfluenceConnector().fetch(source)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="advisory locks require PostgreSQL")
def test_source_advisory_lock_excludes_second_database_session(source: Source) -> None:
    import psycopg

    with source_lock(source.pk) as first_acquired:
        assert first_acquired
        lock_name = f"agenthub:ingestion-source:{source.pk}"
        with psycopg.connect(**connection.get_connection_params()) as second:
            with second.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [lock_name])
                row = cursor.fetchone()
                assert row is not None and row[0] is False

    with psycopg.connect(**connection.get_connection_params()) as second:
        with second.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [lock_name])
            row = cursor.fetchone()
            assert row is not None and row[0] is True
            cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [lock_name])
