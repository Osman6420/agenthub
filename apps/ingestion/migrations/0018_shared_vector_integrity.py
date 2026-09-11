"""Fixed search indexes, FORCE RLS and immutable generation-scoped writes.

No runtime DDL is introduced. Reversal removes the new protections/indexes only;
reversing the preceding table migration is a separately reviewed destructive step.
"""

from django.db import migrations


_INTEGRITY = r"""
ALTER TABLE public.ingestion_sharedvectorchunk ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingestion_sharedvectorchunk FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON public.ingestion_sharedvectorchunk
USING (public.agenthub_tenant_scope_contains(organization_id))
WITH CHECK (public.agenthub_tenant_scope_contains(organization_id));

ALTER TABLE public.ingestion_sharedvectorchunk ADD CONSTRAINT shared_vector_actual_dimensions
CHECK (public.vector_dims(embedding) = dimensions);

CREATE FUNCTION public.agenthub_shared_vector_integrity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE
    generation record;
    importing boolean;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_CHUNK_IMMUTABLE';
    END IF;
    SELECT * INTO generation FROM public.ingestion_indexversion
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.index_version_id ELSE NEW.index_version_id END
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SHARED_CHUNK_GENERATION_INVALID';
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF generation.organization_id <> OLD.organization_id OR generation.status = 'active'
           OR generation.storage_state <> 'retired' THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_CHUNK_RETIRE_REQUIRED';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.releases_scenariorelease r
            WHERE r.organization_id = generation.organization_id AND (
                r.manifest->'index_versions' @> jsonb_build_array(generation.id)
                OR r.manifest->'document_set_versions' @> jsonb_build_array(generation.document_set_version_id)
            )
        ) OR EXISTS (
            SELECT 1 FROM public.evaluations_questionevaluationrun e
            WHERE e.organization_id = generation.organization_id AND e.index_version_id = generation.id
        ) OR EXISTS (
            SELECT 1 FROM public.ingestion_stagedindexbuildjob j
            WHERE j.organization_id = generation.organization_id
              AND j.document_set_version_id = generation.document_set_version_id
              AND j.status IN ('dispatch_pending', 'queued', 'running', 'reconciliation_required')
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_CHUNK_REFERENCED';
        END IF;
        RETURN OLD;
    END IF;
    -- Only the migration/table-owner role may import already sealed legacy rows.
    -- A caller-controlled setting alone never enables this exception.
    SELECT current_setting('app.shared_vector_backfill', true) = 'on'
       AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
    INTO importing FROM pg_class c WHERE c.oid = 'public.ingestion_sharedvectorchunk'::regclass;
    IF NOT COALESCE(importing, false) AND (
        generation.status <> 'building' OR generation.storage_layout <> 'shared_v1'
        OR generation.storage_state <> 'open'
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_CHUNK_NOT_WRITABLE';
    END IF;
    IF generation.organization_id <> NEW.organization_id
       OR COALESCE(generation.dimensions, 64) <> NEW.dimensions
       OR COALESCE(NULLIF(generation.index_type, ''), 'vector') <> NEW.representation THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SHARED_CHUNK_SCOPE_GEOMETRY';
    END IF;
    IF NEW.document_version_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.documents_documentversion d
            JOIN public.documents_document p ON p.id = d.document_id
            JOIN public.documents_documentsetmembership m ON m.document_version_id = d.id
            JOIN public.documents_documentsetversion s ON s.id = m.document_set_version_id
            JOIN public.documents_documentset collection ON collection.id = s.document_set_id
            WHERE d.id = NEW.document_version_id
              AND d.organization_id = NEW.organization_id AND p.organization_id = NEW.organization_id
              AND m.organization_id = NEW.organization_id AND s.organization_id = NEW.organization_id
              AND collection.organization_id = NEW.organization_id
              AND s.id = generation.document_set_version_id
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SHARED_CHUNK_DOCUMENT_SCOPE';
        END IF;
    ELSIF NEW.indexed_document_id IS NOT NULL THEN
        IF generation.document_set_version_id IS NOT NULL OR (
            generation.source_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.ingestion_source source
                WHERE source.id = generation.source_id
                  AND source.organization_id = generation.organization_id
            )
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SHARED_CHUNK_DOCUMENT_SCOPE';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.ingestion_indexeddocument d
            WHERE d.id = NEW.indexed_document_id AND d.organization_id = NEW.organization_id
              AND d.index_version_id = generation.id
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SHARED_CHUNK_DOCUMENT_SCOPE';
        END IF;
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER shared_vector_integrity BEFORE INSERT OR UPDATE OR DELETE
ON public.ingestion_sharedvectorchunk FOR EACH ROW
EXECUTE FUNCTION public.agenthub_shared_vector_integrity();

CREATE FUNCTION public.agenthub_shared_generation_integrity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
BEGIN
    IF OLD.storage_layout = 'legacy' AND NEW.storage_layout = 'shared_v1' AND NOT EXISTS (
        SELECT 1 FROM pg_class c WHERE c.oid = 'public.ingestion_sharedvectorchunk'::regclass
        AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'SHARED_BACKFILL_OWNER_REQUIRED';
    END IF;
    IF OLD.storage_layout = 'shared_v1' THEN
        IF ROW(NEW.organization_id, NEW.source_id, NEW.document_set_version_id,
               NEW.embedding_profile_id, NEW.dimensions, NEW.index_type, NEW.version,
               NEW.pipeline_fingerprint, NEW.chunking_profile_id, NEW.retrieval_profile_id,
               NEW.summary_model_profile_id, NEW.summary_prompt_contract_id,
               NEW.parent_index_version_id, NEW.storage_layout)
           IS DISTINCT FROM
           ROW(OLD.organization_id, OLD.source_id, OLD.document_set_version_id,
               OLD.embedding_profile_id, OLD.dimensions, OLD.index_type, OLD.version,
               OLD.pipeline_fingerprint, OLD.chunking_profile_id, OLD.retrieval_profile_id,
               OLD.summary_model_profile_id, OLD.summary_prompt_contract_id,
               OLD.parent_index_version_id, OLD.storage_layout) THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_GENERATION_IMMUTABLE';
        END IF;
        IF NEW.storage_state IS DISTINCT FROM OLD.storage_state AND NOT (
            (OLD.storage_state = 'new' AND NEW.storage_state IN ('open', 'retired'))
            OR (OLD.storage_state = 'open' AND NEW.storage_state IN ('sealed', 'retired'))
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_GENERATION_STATE_INVALID';
        END IF;
        -- Retention of sealed data needs the complete reference-aware cutover. Until
        -- then only failed/unserved builds can retire; no historical citation is lost.
        IF NEW.storage_state = 'retired' AND (NEW.store_ready OR NEW.status = 'active') THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SHARED_CHUNK_RETENTION_REQUIRED';
        END IF;
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER shared_generation_integrity BEFORE UPDATE ON public.ingestion_indexversion
FOR EACH ROW EXECUTE FUNCTION public.agenthub_shared_generation_integrity();
"""

_INDEXES = (
    ("shared_vec_64_cos", "vector", 64),
    ("shared_vec_768_cos", "vector", 768),
    ("shared_vec_1536_cos", "vector", 1536),
    ("shared_half_3072_cos", "halfvec", 3072),
    ("shared_half_4000_cos", "halfvec", 4000),
)


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        version = cursor.fetchone()
        if not version or tuple(int(value) for value in version[0].split('.')[:2]) < (0, 8):
            raise RuntimeError("SHARED_VECTOR_REQUIRES_PGVECTOR_0_8")
        cursor.execute(_INTEGRITY)
        for name, representation, dimensions in _INDEXES:
            cursor.execute(
                f"CREATE INDEX {name} ON public.ingestion_sharedvectorchunk "
                f"USING hnsw ((embedding::public.{representation}({dimensions})) "
                f"public.{representation}_cosine_ops) WITH (m=16, ef_construction=64) "
                f"WHERE dimensions = {dimensions} AND representation = '{representation}'"
            )
        cursor.execute(
            "CREATE INDEX shared_chunk_fts ON public.ingestion_sharedvectorchunk "
            "USING gin (to_tsvector('simple', text))"
        )


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER shared_generation_integrity ON public.ingestion_indexversion")
        cursor.execute("DROP FUNCTION public.agenthub_shared_generation_integrity()")
        cursor.execute("DROP TRIGGER shared_vector_integrity ON public.ingestion_sharedvectorchunk")
        cursor.execute("DROP FUNCTION public.agenthub_shared_vector_integrity()")
        cursor.execute("DROP POLICY tenant_isolation ON public.ingestion_sharedvectorchunk")
        cursor.execute("ALTER TABLE public.ingestion_sharedvectorchunk NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE public.ingestion_sharedvectorchunk DISABLE ROW LEVEL SECURITY")
        cursor.execute(
            "ALTER TABLE public.ingestion_sharedvectorchunk "
            "DROP CONSTRAINT shared_vector_actual_dimensions"
        )
        for name, _, _ in _INDEXES:
            cursor.execute(f"DROP INDEX public.{name}")
        cursor.execute("DROP INDEX public.shared_chunk_fts")


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0017_shared_vector_chunk_foundation"),
        ("evaluations", "0005_questioncase_expected_answer"),
    ]
    operations = [migrations.RunPython(install, reverse)]
