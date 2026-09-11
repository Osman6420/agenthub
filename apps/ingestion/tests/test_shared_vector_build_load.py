"""Real prepared query plans while another connection builds in the shared table."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import perf_counter

import numpy as np
import pytest
from django.db import close_old_connections, connection, transaction

from apps.ingestion import vector_store
from apps.ingestion.models import IndexedDocument, IndexVersion
from apps.ingestion.tests.test_shared_vector_storage import _generation
from apps.ingestion.tests.test_shared_vector_workload import _plan_shape
from apps.ingestion.vector_store import VectorRow

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql"
        or os.environ.get("AGENTHUB_SHARED_VECTOR_BENCHMARK") != "1",
        reason="explicit isolated PostgreSQL workload opt-in required",
    ),
]


def test_generic_and_custom_plans_under_concurrent_build():
    assert str(connection.settings_dict["NAME"]).startswith("test_")
    rng = np.random.default_rng(20260911)
    selected, document = _generation("build-load")
    vectors = rng.normal(size=(2200, 64)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    def rows(index, doc, matrix, offset):
        return [
            VectorRow(
                index.organization_id,
                None,
                offset + n,
                f"synthetic-{index.pk}-{offset + n}",
                value.tolist(),
                indexed_document_id=doc.pk,
            )
            for n, value in enumerate(matrix)
        ]

    for start in range(0, len(vectors), 100):
        vector_store.write_chunks(
            selected, rows(selected, document, vectors[start : start + 100], start)
        )
    IndexVersion.objects.filter(pk=selected.pk).update(
        status="promotable",
        storage_state="sealed",
        store_ready=True,
        chunk_count=len(vectors),
    )
    selected.refresh_from_db()
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE ingestion_sharedvectorchunk")
    report = []
    for mode in ("force_generic_plan", "force_custom_plan"):
        building = IndexVersion.objects.create(
            organization_id=selected.organization_id,
            version=2,
            dimensions=64,
            index_type="vector",
            storage_layout="shared_v1",
            storage_state="open",
            status="building",
        )
        build_doc = IndexedDocument.objects.create(
            organization_id=selected.organization_id,
            index_version=building,
            source_uri=f"synthetic:{mode}",
            checksum="b" * 64,
        )
        barrier = Barrier(2)
        batch = vectors[:100]

        def writer(barrier, building, build_doc, batch):
            close_old_connections()
            try:
                for iteration in range(43):
                    barrier.wait(30)
                    vector_store.write_chunks(
                        building, rows(building, build_doc, batch, iteration * 100)
                    )
                    barrier.wait(30)
            finally:
                connection.close()

        prepared, last_params = False, None

        def execute_prepared(execute, sql, params, many, context):
            nonlocal prepared, last_params
            if sql.startswith("SELECT document_version_id, ordinal, text, chunk_kind,"):
                if not prepared:
                    parts = sql.split("%s")
                    assert len(parts) == len(params) + 1
                    bound = parts[0] + "".join(f"${n}{part}" for n, part in enumerate(parts[1:], 1))
                    execute("PREPARE shared_load_query AS " + bound, None, False, context)
                    prepared = True
                last_params = params
                return execute(
                    "EXECUTE shared_load_query(" + ",".join(["%s"] * len(params)) + ")",
                    params,
                    many,
                    context,
                )
            return execute(sql, params, many, context)

        timings, recalls = [], []
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('plan_cache_mode', %s, false)", [mode])
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(writer, barrier, building, build_doc, batch)
                try:
                    for iteration in range(43):
                        query = rng.normal(size=64).astype(np.float32)
                        query /= np.linalg.norm(query)
                        expected = set(
                            np.argsort(np.einsum("ij,j->i", vectors, query))[-10:].tolist()
                        )
                        barrier.wait(30)
                        started = perf_counter()
                        with connection.execute_wrapper(execute_prepared):
                            hits = vector_store.search(
                                selected,
                                query.tolist(),
                                organization_id=selected.organization_id,
                                top_k=10,
                            )
                        elapsed = (perf_counter() - started) * 1000
                        barrier.wait(30)
                        assert len(hits) == 10
                        assert all(hit.indexed_document_id == document.pk for hit in hits)
                        if iteration >= 3:
                            timings.append(elapsed)
                            recalls.append(len(expected & {hit.ordinal for hit in hits}) / 10)
                    pending.result(timeout=30)
                finally:
                    barrier.abort()
            with transaction.atomic(), connection.cursor() as cursor:
                # Keep the DAL's transaction-local planning and RLS settings for EXPLAIN.
                vector_store.search(
                    selected,
                    query.tolist(),
                    organization_id=selected.organization_id,
                    top_k=10,
                )
                cursor.execute(
                    "SELECT generic_plans, custom_plans FROM pg_prepared_statements "
                    "WHERE name='shared_load_query'"
                )
                generic, custom = cursor.fetchone()
                # The DAL must override a pool's generic-plan preference for shared ANN.
                assert generic == 0 and custom >= 43
                cursor.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) EXECUTE shared_load_query("
                    + ",".join(["%s"] * len(last_params))
                    + ")",
                    last_params,
                )
                shape = _plan_shape(cursor.fetchone()[0][0]["Plan"])
            report.append(
                {
                    "mode": mode,
                    "generic_plans": generic,
                    "custom_plans": custom,
                    "concurrent_written_chunks": building.shared_chunks.count(),
                    "recall_at_10": float(np.mean(recalls)),
                    "p50_ms": float(np.percentile(timings, 50)),
                    "p95_ms": float(np.percentile(timings, 95)),
                    "plan": shape,
                }
            )
        finally:
            with connection.cursor() as cursor:
                if prepared:
                    cursor.execute("DEALLOCATE shared_load_query")
                cursor.execute("RESET plan_cache_mode")
    Path(".tmp/shared-vector-build-load.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    for result in report:
        assert result["concurrent_written_chunks"] == 4300
        assert result["recall_at_10"] >= 0.95
        assert result["p50_ms"] <= 80 and result["p95_ms"] <= 200
