"""Keep connector lineage and compatibility status under one job authority."""

from django.db import migrations

FORWARD = r"""
CREATE FUNCTION public.agenthub_ingestion_job_lineage() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE src record; run record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.kind <> 'index_build' THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INGESTION_JOB_IMMUTABLE';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND ROW(
        NEW.kind, NEW.source_id, NEW.rest_sync_run_id, NEW.confluence_sync_run_id,
        NEW.source_config_checksum, NEW.organization_id
    ) IS DISTINCT FROM ROW(
        OLD.kind, OLD.source_id, OLD.rest_sync_run_id, OLD.confluence_sync_run_id,
        OLD.source_config_checksum, OLD.organization_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INGESTION_JOB_IMMUTABLE';
    END IF;
    IF NEW.kind = 'index_build' THEN RETURN NEW; END IF;
    IF TG_OP = 'UPDATE' AND ROW(NEW.request_checksum, NEW.pipeline_fingerprint,
        NEW.requested_by, NEW.max_attempts) IS DISTINCT FROM ROW(
        OLD.request_checksum, OLD.pipeline_fingerprint, OLD.requested_by, OLD.max_attempts
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INGESTION_JOB_IMMUTABLE';
    END IF;
    -- Current source configuration may be disabled or edited after admission. Workers
    -- fail on its checksum; that must not prevent recording the job's failure itself.
    IF TG_OP = 'UPDATE' THEN RETURN NEW; END IF;
    SELECT * INTO src FROM public.ingestion_source WHERE id = NEW.source_id FOR UPDATE;
    IF NOT FOUND OR src.organization_id <> NEW.organization_id
       OR src.connection_id IS NULL OR src.document_set_id IS NULL
       OR NOT EXISTS (SELECT 1 FROM public.documents_documentset d
           WHERE d.id = src.document_set_id AND d.organization_id = NEW.organization_id) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'INGESTION_JOB_SOURCE_INVALID';
    END IF;
    IF NEW.kind = 'rest_sync' THEN
        SELECT * INTO run FROM public.ingestion_restsyncrun WHERE id = NEW.rest_sync_run_id;
        IF NOT FOUND OR run.organization_id <> NEW.organization_id OR run.source_id <> src.id
           OR src.connector_type <> 'generic_rest'
           OR run.rest_profile_id IS DISTINCT FROM src.rest_profile_id
           OR run.rest_contract_id IS DISTINCT FROM src.rest_contract_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'INGESTION_JOB_RUN_INVALID';
        END IF;
    ELSIF NEW.kind = 'confluence_sync' THEN
        SELECT * INTO run FROM public.ingestion_confluencesyncrun
        WHERE id = NEW.confluence_sync_run_id;
        IF NOT FOUND OR run.organization_id <> NEW.organization_id OR run.source_id <> src.id
           OR src.connector_type <> 'confluence_dc'
           OR run.confluence_profile_id IS DISTINCT FROM src.confluence_profile_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'INGESTION_JOB_RUN_INVALID';
        END IF;
    ELSE
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'INGESTION_JOB_KIND_INVALID';
    END IF;
    IF TG_OP = 'INSERT' AND (run.status <> 'queued' OR run.attempt <> 0
       OR NEW.status <> 'dispatch_pending' OR NEW.attempt <> 0) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INGESTION_JOB_ADMISSION_INVALID';
    END IF;
    IF EXISTS (SELECT 1 FROM public.ingestion_restsyncrun r
        WHERE r.source_id = src.id AND r.id IS DISTINCT FROM NEW.rest_sync_run_id
          AND r.status IN ('queued','running','retry'))
       OR EXISTS (SELECT 1 FROM public.ingestion_confluencesyncrun r
        WHERE r.source_id = src.id AND r.id IS DISTINCT FROM NEW.confluence_sync_run_id
          AND r.status IN ('queued','running','retry')) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SOURCE_BUSY';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER ingestion_job_lineage
BEFORE INSERT OR UPDATE OR DELETE ON public.ingestion_stagedindexbuildjob
FOR EACH ROW EXECUTE FUNCTION public.agenthub_ingestion_job_lineage();

CREATE FUNCTION public.agenthub_connector_job_projection() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE job record; run record; expected_status text;
BEGIN
    IF TG_TABLE_NAME = 'ingestion_stagedindexbuildjob' THEN
        SELECT * INTO job FROM public.ingestion_stagedindexbuildjob WHERE id = NEW.id;
    ELSIF TG_TABLE_NAME = 'ingestion_restsyncrun' THEN
        SELECT * INTO job FROM public.ingestion_stagedindexbuildjob WHERE rest_sync_run_id = NEW.id;
    ELSE
        SELECT * INTO job FROM public.ingestion_stagedindexbuildjob
        WHERE confluence_sync_run_id = NEW.id;
    END IF;
    IF NOT FOUND OR job.kind = 'index_build' THEN RETURN NULL; END IF;
    IF job.kind = 'rest_sync' THEN
        SELECT * INTO run FROM public.ingestion_restsyncrun WHERE id = job.rest_sync_run_id;
    ELSE
        SELECT * INTO run FROM public.ingestion_confluencesyncrun
        WHERE id = job.confluence_sync_run_id;
    END IF;
    expected_status := CASE job.status
        WHEN 'dispatch_pending' THEN 'queued' WHEN 'queued' THEN 'queued'
        WHEN 'running' THEN 'running' WHEN 'retry_wait' THEN 'retry'
        WHEN 'succeeded' THEN 'succeeded' ELSE 'dead_letter' END;
    IF NOT FOUND OR run.organization_id <> job.organization_id OR run.source_id <> job.source_id
       OR run.status IS DISTINCT FROM expected_status
       OR run.attempt IS DISTINCT FROM job.attempt
       OR run.max_attempts IS DISTINCT FROM job.max_attempts
       OR run.error_code IS DISTINCT FROM job.error_code THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'INGESTION_JOB_PROJECTION_MISMATCH';
    END IF;
    RETURN NULL;
END
$body$;
CREATE CONSTRAINT TRIGGER connector_job_projection
AFTER INSERT OR UPDATE ON public.ingestion_stagedindexbuildjob
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.agenthub_connector_job_projection();
CREATE CONSTRAINT TRIGGER rest_job_projection
AFTER INSERT OR UPDATE ON public.ingestion_restsyncrun
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.agenthub_connector_job_projection();
CREATE CONSTRAINT TRIGGER confluence_job_projection
AFTER INSERT OR UPDATE ON public.ingestion_confluencesyncrun
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.agenthub_connector_job_projection();

CREATE FUNCTION public.agenthub_connector_run_lineage() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE linked boolean;
BEGIN
    IF TG_TABLE_NAME = 'ingestion_restsyncrun' THEN
        SELECT EXISTS (SELECT 1 FROM public.ingestion_stagedindexbuildjob
            WHERE rest_sync_run_id = OLD.id) INTO linked;
    ELSE
        SELECT EXISTS (SELECT 1 FROM public.ingestion_stagedindexbuildjob
            WHERE confluence_sync_run_id = OLD.id) INTO linked;
    END IF;
    IF linked AND (TG_OP = 'DELETE' OR
       (to_jsonb(NEW) - ARRAY['status','attempt','error_code','started_at',
         'finished_at','updated_at',
         'snapshot_complete','material_change','discovered_count','changed_count','unchanged_count',
         'missing_count','fetched_bytes','candidate_set_version_id']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status','attempt','error_code','started_at',
         'finished_at','updated_at',
         'snapshot_complete','material_change','discovered_count','changed_count','unchanged_count',
         'missing_count','fetched_bytes','candidate_set_version_id'])) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INGESTION_RUN_LINEAGE_IMMUTABLE';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$body$;
CREATE TRIGGER a_rest_run_lineage BEFORE UPDATE OR DELETE ON public.ingestion_restsyncrun
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_run_lineage();
CREATE TRIGGER a_confluence_run_lineage
BEFORE UPDATE OR DELETE ON public.ingestion_confluencesyncrun
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_run_lineage();

CREATE FUNCTION public.agenthub_connector_evidence_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE job record; projected boolean := false; finishing boolean := false;
BEGIN
    IF TG_TABLE_NAME = 'ingestion_restsyncrun' THEN
        SELECT * INTO job FROM public.ingestion_stagedindexbuildjob
        WHERE rest_sync_run_id = NEW.id FOR SHARE;
        projected := true;
    ELSIF TG_TABLE_NAME = 'ingestion_confluencesyncrun' THEN
        SELECT * INTO job FROM public.ingestion_stagedindexbuildjob
        WHERE confluence_sync_run_id = NEW.id FOR SHARE;
        projected := true;
    ELSE
        -- Fence even an old cursor's missing/unchanged update during a new snapshot.
        SELECT * INTO job FROM public.ingestion_stagedindexbuildjob
        WHERE source_id = NEW.source_id
          AND status IN ('dispatch_pending','queued','running','retry_wait',
                         'reconciliation_required')
        FOR SHARE;
    END IF;
    IF NOT FOUND THEN RETURN NEW; END IF;
    IF projected AND (to_jsonb(NEW) - ARRAY['status','attempt','error_code','started_at',
        'finished_at','updated_at']) IS NOT DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['status','attempt','error_code','started_at',
        'finished_at','updated_at']) THEN RETURN NEW; END IF;
    IF projected THEN
        finishing := job.status = 'succeeded' AND OLD.status = 'running'
                     AND NEW.status = 'succeeded' AND NEW.snapshot_complete;
    END IF;
    IF job.organization_id <> NEW.organization_id OR job.source_id <> NEW.source_id
       OR current_setting('app.ingestion_job_id', true) IS DISTINCT FROM job.id::text
       OR current_setting('app.ingestion_job_attempt', true) IS DISTINCT FROM job.attempt::text
       OR (job.status <> 'running' AND NOT finishing) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'CONNECTOR_EVIDENCE_FENCED';
    END IF;
    IF projected THEN
      IF NEW.candidate_set_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.documents_documentsetversion v
        JOIN public.ingestion_source s ON s.document_set_id = v.document_set_id
        WHERE v.id = NEW.candidate_set_version_id AND v.organization_id = job.organization_id
          AND s.id = job.source_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'CONNECTOR_CANDIDATE_SCOPE_INVALID';
      END IF;
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER rest_job_evidence BEFORE UPDATE ON public.ingestion_restsyncrun
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_evidence_guard();
CREATE TRIGGER confluence_job_evidence BEFORE UPDATE ON public.ingestion_confluencesyncrun
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_evidence_guard();
CREATE TRIGGER rest_cursor_job_evidence
BEFORE INSERT OR UPDATE ON public.ingestion_restdocumentcursor
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_evidence_guard();
CREATE TRIGGER confluence_cursor_job_evidence
BEFORE INSERT OR UPDATE ON public.ingestion_confluencedocumentcursor
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_evidence_guard();

CREATE FUNCTION public.agenthub_connector_source_writer() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
BEGIN
    PERFORM 1 FROM public.tenancy_organization WHERE id = NEW.organization_id FOR NO KEY UPDATE;
    PERFORM 1 FROM public.ingestion_source
    WHERE id = NEW.source_id AND organization_id = NEW.organization_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'INGESTION_RUN_SOURCE_INVALID';
    END IF;
    IF EXISTS (SELECT 1 FROM public.ingestion_stagedindexbuildjob
        WHERE source_id = NEW.source_id AND status IN (
            'dispatch_pending','queued','running','retry_wait','reconciliation_required'
        )) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SOURCE_BUSY';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER rest_source_writer BEFORE INSERT ON public.ingestion_restsyncrun
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_source_writer();
CREATE TRIGGER confluence_source_writer BEFORE INSERT ON public.ingestion_confluencesyncrun
FOR EACH ROW EXECUTE FUNCTION public.agenthub_connector_source_writer();
"""

REVERSE = r"""
DROP TRIGGER confluence_source_writer ON public.ingestion_confluencesyncrun;
DROP TRIGGER rest_source_writer ON public.ingestion_restsyncrun;
DROP FUNCTION public.agenthub_connector_source_writer();
DROP TRIGGER confluence_cursor_job_evidence ON public.ingestion_confluencedocumentcursor;
DROP TRIGGER rest_cursor_job_evidence ON public.ingestion_restdocumentcursor;
DROP TRIGGER confluence_job_evidence ON public.ingestion_confluencesyncrun;
DROP TRIGGER rest_job_evidence ON public.ingestion_restsyncrun;
DROP FUNCTION public.agenthub_connector_evidence_guard();
DROP TRIGGER a_confluence_run_lineage ON public.ingestion_confluencesyncrun;
DROP TRIGGER a_rest_run_lineage ON public.ingestion_restsyncrun;
DROP FUNCTION public.agenthub_connector_run_lineage();
DROP TRIGGER confluence_job_projection ON public.ingestion_confluencesyncrun;
DROP TRIGGER rest_job_projection ON public.ingestion_restsyncrun;
DROP TRIGGER connector_job_projection ON public.ingestion_stagedindexbuildjob;
DROP FUNCTION public.agenthub_connector_job_projection();
DROP TRIGGER ingestion_job_lineage ON public.ingestion_stagedindexbuildjob;
DROP FUNCTION public.agenthub_ingestion_job_lineage();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0022_typed_ingestion_job")]
    operations = [migrations.RunPython(install, reverse)]
