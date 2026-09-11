"""Opt-in reproducible 20k workload; never run against an application database.

Run with AGENTHUB_SHARED_VECTOR_BENCHMARK=1 and the isolated PostgreSQL pytest
profile. Thresholds were recorded in Agent_Hub_MD/plan.md before measurement.
"""

import json
import os
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest
from django.db import connection, transaction

from apps.ingestion import vector_store
from apps.ingestion.models import IndexedDocument, IndexVersion
from apps.ingestion.tests.test_shared_vector_storage import _generation
from apps.ingestion.vector_store import VectorRow

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql"
        or os.environ.get("AGENTHUB_SHARED_VECTOR_BENCHMARK") != "1",
        reason="explicit isolated PostgreSQL workload opt-in required",
    ),
]


def _plan_shape(plan):
    allowed = {
        "Node Type",
        "Index Name",
        "Plan Rows",
        "Actual Rows",
        "Actual Total Time",
        "Shared Hit Blocks",
        "Shared Read Blocks",
    }
    result = {key: value for key, value in plan.items() if key in allowed}
    if plan.get("Plans"):
        result["Plans"] = [_plan_shape(child) for child in plan["Plans"]]
    return result


def _explain(index, query):
    captured = []

    def remember(execute, sql, params, many, context):
        if sql.startswith("SELECT document_version_id, ordinal, text, chunk_kind,"):
            captured.append((sql, params))
        return execute(sql, params, many, context)

    with transaction.atomic():
        with connection.execute_wrapper(remember):
            vector_store.search(index, query, organization_id=index.organization_id, top_k=10)
        assert len(captured) == 1
        with connection.cursor() as cursor:
            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + captured[0][0], captured[0][1]
            )
            return _plan_shape(cursor.fetchone()[0][0]["Plan"])


def test_shared_vector_workload():
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    rng = np.random.default_rng(20260909)
    cases = []
    for ordinal, size in enumerate((100, 1900, 8000, 10000)):
        seeded_at = perf_counter()
        shared, document = _generation(f"perf-{ordinal}")
        legacy = IndexVersion.objects.create(
            organization_id=shared.organization_id,
            dimensions=64,
            index_type="vector",
            version=2,
            storage_layout="legacy",
        )
        vector_store.provision_store(legacy)
        vectors = rng.normal(size=(size, 64)).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        for start in range(0, size, 500):
            batch = [
                VectorRow(
                    shared.organization_id,
                    None,
                    i,
                    f"synthetic-{i}",
                    vectors[i].tolist(),
                    indexed_document_id=document.pk,
                )
                for i in range(start, min(start + 500, size))
            ]
            vector_store.write_chunks(shared, batch)
            vector_store.write_chunks(legacy, batch)
        shared.status = "promotable"
        shared.storage_state = "sealed"
        shared.store_ready = True
        shared.chunk_count = size
        shared.save(update_fields=["status", "storage_state", "store_ready", "chunk_count"])
        cases.append((shared, legacy, vectors))
        print(
            f"Seeded {size} rows in both layouts in {perf_counter() - seeded_at:.2f}s", flush=True
        )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE ingestion_sharedvectorchunk")
        for _, legacy, _ in cases:
            cursor.execute(f'ANALYZE "{vector_store.store_name(legacy)}"')  # noqa: S608
    report = []
    for shared, legacy, vectors in cases:
        document_id = shared.documents.get().pk
        timings: dict[str, list[float]] = {"shared": [], "legacy": []}
        recalls = []
        for iteration in range(43):
            query = rng.normal(size=64).astype(np.float32)
            query /= np.linalg.norm(query)
            # A single-thread reference avoids BLAS worker spin competing with PostgreSQL.
            expected = set(np.argsort(np.einsum("ij,j->i", vectors, query))[-10:].tolist())
            for label, index in (("legacy", legacy), ("shared", shared)):
                started = perf_counter()
                hits = vector_store.search(
                    index,
                    query.tolist(),
                    organization_id=index.organization_id,
                    top_k=10,
                )
                elapsed = (perf_counter() - started) * 1000
                if iteration >= 3:
                    timings[label].append(elapsed)
                    if label == "shared":
                        recalls.append(len(expected & {hit.ordinal for hit in hits}) / 10)
                assert all(hit.text == f"synthetic-{hit.ordinal}" for hit in hits)
                if label == "shared":
                    assert all(hit.indexed_document_id == document_id for hit in hits)
        row = {"size": len(vectors), "recall_at_10": float(np.mean(recalls))}
        for label in timings:
            row[f"{label}_p50_ms"] = float(np.percentile(timings[label], 50))
            row[f"{label}_p95_ms"] = float(np.percentile(timings[label], 95))
        row["p95_ratio"] = row["shared_p95_ms"] / row["legacy_p95_ms"]
        row["shared_plan"] = _explain(shared, query.tolist())
        row["legacy_plan"] = _explain(legacy, query.tolist())
        report.append(row)
    output = Path(".tmp/shared-vector-workload.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    for row in report:
        assert row["recall_at_10"] >= 0.95
        assert row["shared_p50_ms"] <= 80 and row["shared_p95_ms"] <= 200
        assert row["p95_ratio"] <= 1.5


def test_mixed_geometry_with_retained_generations_and_foreign_tenants():
    """Retained generations and other embedding spaces must not dilute the selected scope."""
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    rng = np.random.default_rng(20260910)
    cases = []

    def populate(index, document, size, *, retained=False):
        vectors = rng.normal(size=(size, index.dimensions)).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        # Match the persisted half precision, including its slightly changed norm.
        if index.index_type == "halfvec":
            vectors = vectors.astype(np.float16).astype(np.float32)
        for start in range(0, size, 100):
            vector_store.write_chunks(
                index,
                [
                    VectorRow(
                        index.organization_id,
                        None,
                        ordinal,
                        f"synthetic-{index.pk}-{ordinal}",
                        vectors[ordinal].tolist(),
                        indexed_document_id=document.pk,
                    )
                    for ordinal in range(start, min(start + 100, size))
                ],
            )
        index.status = "superseded" if retained else "promotable"
        index.storage_state = "sealed"
        index.store_ready = True
        index.chunk_count = size
        index.save(update_fields=["status", "storage_state", "store_ready", "chunk_count"])
        return vectors

    for dimensions, representation in (
        (64, "vector"),
        (768, "vector"),
        (1536, "vector"),
        (3072, "halfvec"),
        (4000, "halfvec"),
    ):
        started = perf_counter()
        selected, document = _generation(f"mixed-{dimensions}", dimensions, representation)
        vectors = populate(selected, document, 2200 if dimensions == 64 else 256)
        for version in range(2, 18):
            old = IndexVersion.objects.create(
                organization_id=selected.organization_id,
                version=version,
                dimensions=dimensions,
                index_type=representation,
                storage_layout="shared_v1",
                storage_state="open",
                status="building",
            )
            old_document = IndexedDocument.objects.create(
                organization_id=selected.organization_id,
                index_version=old,
                source_uri=f"synthetic:old-{dimensions}-{version}",
                checksum="b" * 64,
            )
            populate(old, old_document, 64, retained=True)
        foreign, foreign_document = _generation(f"foreign-{dimensions}", dimensions, representation)
        populate(foreign, foreign_document, 256)
        cases.append((selected, document, vectors, foreign.organization_id))
        print(f"Mixed {dimensions} geometry seeded in {perf_counter() - started:.2f}s", flush=True)
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE ingestion_sharedvectorchunk")

    report = []
    for selected, document, vectors, foreign_org in cases:
        timings, recalls = [], []
        for iteration in range(43):
            query = rng.normal(size=selected.dimensions).astype(np.float32)
            query /= np.linalg.norm(query)
            if selected.index_type == "halfvec":
                query = query.astype(np.float16).astype(np.float32)
            scores = np.einsum("ij,j->i", vectors, query) / np.linalg.norm(vectors, axis=1)
            expected = set(np.argsort(scores)[-10:].tolist())
            started = perf_counter()
            hits = vector_store.search(
                selected,
                query.tolist(),
                organization_id=selected.organization_id,
                top_k=10,
            )
            elapsed = (perf_counter() - started) * 1000
            assert len(hits) == 10
            assert all(hit.indexed_document_id == document.pk for hit in hits)
            assert all(hit.text == f"synthetic-{selected.pk}-{hit.ordinal}" for hit in hits)
            if iteration >= 3:
                timings.append(elapsed)
                recalls.append(len(expected & {hit.ordinal for hit in hits}) / 10)
        assert not vector_store.search(
            selected,
            query.tolist(),
            organization_id=foreign_org,
            top_k=10,
        )
        report.append(
            {
                "dimensions": selected.dimensions,
                "representation": selected.index_type,
                "selected_chunks": len(vectors),
                "retained_generations": 16,
                "recall_at_10": float(np.mean(recalls)),
                "p50_ms": float(np.percentile(timings, 50)),
                "p95_ms": float(np.percentile(timings, 95)),
                "plan": _explain(selected, query.tolist()),
            }
        )
    output = Path(".tmp/shared-vector-mixed-workload.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    for row in report:
        assert row["recall_at_10"] >= 0.95
        assert row["p50_ms"] <= 80 and row["p95_ms"] <= 200
