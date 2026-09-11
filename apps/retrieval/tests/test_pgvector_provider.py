from __future__ import annotations

import pytest
from django.db import connection

from apps.ingestion.connectors import CONNECTORS, RawDocument
from apps.ingestion.models import Source
from apps.ingestion.services import create_run, execute_run
from apps.retrieval.providers import PgvectorRetrievalProvider
from apps.tenancy.models import Organization


class FakeConnector:
    def fetch(self, source: Source) -> list[RawDocument]:
        return [
            RawDocument(uri="https://docs.example/returns", content=b"Return policy is 14 days")
        ]


@pytest.mark.django_db
def test_provider_returns_nothing_without_pinned_indexes() -> None:
    result = PgvectorRetrievalProvider().retrieve(
        query="returns", profile={"top_k": 5}, organization_id=1, index_versions=[]
    )
    assert result == []


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="pgvector requires PostgreSQL")
@pytest.mark.parametrize("layout", ["legacy", "shared_v1"])
def test_provider_filters_tenant_and_pinned_index(
    monkeypatch: pytest.MonkeyPatch,
    settings,
    layout,
) -> None:
    settings.INGESTION_VECTOR_STORAGE_LAYOUT = layout
    monkeypatch.setitem(CONNECTORS, "https", FakeConnector)
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    source = Source.objects.create(
        organization=org_a,
        slug="docs",
        name="Docs",
        connector_type="https",
        connector_config={"url": "https://docs.example"},
    )
    run = create_run(source=source)
    execute_run(run.pk, run.organization_id)
    run.refresh_from_db()
    assert run.index_version_id is not None

    provider = PgvectorRetrievalProvider()
    assert (
        provider.retrieve(
            query="return policy",
            profile={"top_k": 3},
            organization_id=org_b.pk,
            index_versions=[run.index_version_id],
        )
        == []
    )
    assert (
        len(
            provider.retrieve(
                query="return policy",
                profile={"top_k": 3},
                organization_id=org_a.pk,
                index_versions=[run.index_version_id],
            )
        )
        == 1
    )
