"""Fence shared writes and sealing with the exact durable build attempt."""

from django.db import migrations

_FORWARD = r"""
CREATE FUNCTION public.agenthub_assert_build_attempt(
    p_request_id bigint, attempt_number integer, tenant_id bigint,
    set_version_id bigint, profile_id bigint, pipeline text
) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE job record;
BEGIN
    IF p_request_id IS NULL THEN RETURN; END IF;
    SELECT * INTO job FROM public.ingestion_stagedindexbuildjob
    WHERE id = p_request_id FOR SHARE;
    IF NOT FOUND OR job.organization_id <> tenant_id OR job.status <> 'running'
       OR job.attempt IS DISTINCT FROM attempt_number
       OR job.document_set_version_id IS DISTINCT FROM set_version_id
       OR job.embedding_profile_id IS DISTINCT FROM profile_id
       OR job.pipeline_fingerprint IS DISTINCT FROM pipeline THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'BUILD_GENERATION_FENCED';
    END IF;
END
$body$;

CREATE FUNCTION public.agenthub_shared_attempt_chunk_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE generation record;
BEGIN
    SELECT * INTO generation FROM public.ingestion_indexversion WHERE id = NEW.index_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'BUILD_GENERATION_FENCED';
    END IF;
    -- Alphabetical trigger order acquires job before shared_vector_integrity locks generation.
    IF generation.storage_layout = 'shared_v1' THEN
        PERFORM public.agenthub_assert_build_attempt(
            generation.build_request_id, generation.build_attempt, generation.organization_id,
            generation.document_set_version_id, generation.embedding_profile_id,
            generation.pipeline_fingerprint
        );
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER a_shared_attempt_chunk BEFORE INSERT ON public.ingestion_sharedvectorchunk
FOR EACH ROW EXECUTE FUNCTION public.agenthub_shared_attempt_chunk_guard();

CREATE FUNCTION public.agenthub_generation_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
BEGIN
    IF TG_OP = 'UPDATE' AND ROW(NEW.build_request_id, NEW.build_attempt)
       IS DISTINCT FROM ROW(OLD.build_request_id, OLD.build_attempt) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'BUILD_ATTEMPT_IMMUTABLE';
    END IF;
    -- Historical completed jobs may migrate only their exact successful result.
    -- This exception neither reopens a generation nor authorizes application writers.
    IF TG_OP = 'UPDATE' AND OLD.storage_layout = 'legacy'
       AND NEW.storage_layout = 'shared_v1' AND NEW.storage_state = 'sealed'
       AND current_setting('app.shared_vector_backfill', true) = 'on'
       AND EXISTS (
           SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
           WHERE c.oid = 'public.ingestion_sharedvectorchunk'::regclass
             AND r.rolname = current_user
       ) THEN
        IF NEW.build_request_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.ingestion_stagedindexbuildjob j
            WHERE j.id = NEW.build_request_id AND j.organization_id = NEW.organization_id
              AND j.attempt = NEW.build_attempt AND j.status = 'succeeded'
              AND j.result_index_version_id = NEW.id
              AND j.document_set_version_id = NEW.document_set_version_id
              AND j.embedding_profile_id = NEW.embedding_profile_id
              AND j.pipeline_fingerprint = NEW.pipeline_fingerprint
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'BUILD_GENERATION_FENCED';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' OR (
        NEW.storage_layout = 'shared_v1' AND TG_OP = 'UPDATE'
        AND NEW.storage_state IS DISTINCT FROM OLD.storage_state
        AND NEW.storage_state IN ('open', 'sealed')
    ) THEN
        PERFORM public.agenthub_assert_build_attempt(
            NEW.build_request_id, NEW.build_attempt, NEW.organization_id,
            NEW.document_set_version_id, NEW.embedding_profile_id, NEW.pipeline_fingerprint
        );
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER generation_attempt_guard BEFORE INSERT OR UPDATE ON public.ingestion_indexversion
FOR EACH ROW EXECUTE FUNCTION public.agenthub_generation_attempt_guard();
"""

_REVERSE = r"""
DROP TRIGGER generation_attempt_guard ON public.ingestion_indexversion;
DROP FUNCTION public.agenthub_generation_attempt_guard();
DROP TRIGGER a_shared_attempt_chunk ON public.ingestion_sharedvectorchunk;
DROP FUNCTION public.agenthub_shared_attempt_chunk_guard();
DROP FUNCTION public.agenthub_assert_build_attempt(bigint, integer, bigint, bigint, bigint, text);
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(_FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(_REVERSE)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0019_generation_build_attempt_fence")]
    operations = [migrations.RunPython(install, reverse)]
