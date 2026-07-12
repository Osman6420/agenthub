"""The ``Document -> IndexedDocument`` rename preserves the relationship structure.

Row/PK preservation is a Django ``RenameModel`` guarantee and is additionally exercised by
the full migration apply in the PostgreSQL ``--create-db`` gate plus the ingestion pipeline
suite (which builds ``IndexedDocument`` + ``Chunk`` rows). This test asserts the retargeted
FK and retrieval-shaped access still work after the rename.
"""

from __future__ import annotations

import pytest

from apps.ingestion.models import Chunk, IndexedDocument, IndexVersion, Source
from apps.ingestion.pipeline import embed_deterministic
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def test_chunk_fk_targets_indexed_document_and_table_renamed() -> None:
    assert Chunk._meta.get_field("document").related_model is IndexedDocument
    assert IndexedDocument._meta.db_table == "ingestion_indexeddocument"


def test_retrieval_shaped_access_after_rename() -> None:
    org = Organization.objects.create(slug="r-org", name="R Org")
    source = Source.objects.create(
        organization=org, slug="s", name="S", connector_type="https", connector_config={}
    )
    index = IndexVersion.objects.create(organization=org, source=source, version=1)
    document = IndexedDocument.objects.create(
        organization=org,
        index_version=index,
        source_uri="https://docs.example/a",
        title="A",
        checksum="c" * 64,
    )
    Chunk.objects.create(
        organization=org,
        index_version=index,
        document=document,
        ordinal=0,
        text="hello",
        embedding=embed_deterministic("hello"),
    )
    # Mirrors PgvectorRetrievalProvider's access pattern.
    chunk = Chunk.objects.select_related("document").get()
    assert chunk.document.source_uri == "https://docs.example/a"
    assert list(document.chunks.all()) == [chunk]
