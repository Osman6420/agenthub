"""Rename the index-scoped ``Document`` build artifact to ``IndexedDocument``.

Phase 2 P2 introduces the content-plane ``apps.documents.Document`` (the tenant's managed
content object). To free the ``Document`` name, the existing Sprint 5 index build artifact is
renamed. ``RenameModel`` renames the table (``ingestion_document`` ->
``ingestion_indexeddocument``) and retargets the ``Chunk.document`` foreign key **in place** —
it preserves every row, primary key, and FK relationship (no drop/recreate). Fully reversible.

SQLite subtlety: renaming a model that a FK points at makes the SQLite schema editor *remake*
the dependent ``ingestion_chunk`` table, and a remake regenerates that table's indexes from the
model state — including the pgvector ``HnswIndex``, whose ``WITH (m = ...)`` DDL is invalid on
SQLite. Migration ``0001`` deliberately kept that index in *state* only (created in the DB via
``RunPython`` on PostgreSQL). So here we drop it from state (no DB op) around the rename and
restore it afterwards; the physical index is untouched on PostgreSQL and never existed on
SQLite. Net state is unchanged, so there is no migration drift.
"""

from __future__ import annotations

import pgvector.django.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(model_name="chunk", name="chunk_embedding_hnsw"),
            ],
            database_operations=[],
        ),
        migrations.RenameModel(old_name="Document", new_name="IndexedDocument"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="chunk",
                    index=pgvector.django.indexes.HnswIndex(
                        ef_construction=64,
                        fields=["embedding"],
                        m=16,
                        name="chunk_embedding_hnsw",
                        opclasses=["vector_cosine_ops"],
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
