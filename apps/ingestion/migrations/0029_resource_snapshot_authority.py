"""Common-job ownership of resource snapshot/cursor evidence, including direct SQL."""

from importlib import import_module

from django.db import migrations


def _legacy_function(name):
    sql = import_module("apps.ingestion.migrations.0023_ingestion_job_authority").FORWARD
    prefix = "CREATE FUNCTION public." + name
    return (prefix + sql.split(prefix, 1)[1].split("$body$;", 1)[0] + "$body$;").replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )


SQL = r"""
CREATE FUNCTION public.agenthub_resource_snapshot_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE owner record;
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND
       (NEW.job_id, NEW.organization_id) IS DISTINCT FROM (OLD.job_id, OLD.organization_id)) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RESOURCE_SNAPSHOT_IMMUTABLE';
    END IF;
    SELECT j.*, s.document_set_id INTO owner FROM public.ingestion_stagedindexbuildjob j
    JOIN public.ingestion_source s ON s.id = j.source_id WHERE j.id = NEW.job_id FOR SHARE OF j;
    IF NOT FOUND OR owner.kind <> 'mcp_resource_sync' OR owner.organization_id <> NEW.organization_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RESOURCE_SNAPSHOT_SCOPE_INVALID';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF owner.status <> 'dispatch_pending' OR owner.attempt <> 0 OR NEW.attempt <> 0
           OR NEW.snapshot_complete OR NEW.material_change OR NEW.candidate_set_version_id IS NOT NULL
           OR NEW.discovered_count <> 0 OR NEW.changed_count <> 0 OR NEW.unchanged_count <> 0
           OR NEW.missing_count <> 0 OR NEW.fetched_bytes <> 0 THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RESOURCE_SNAPSHOT_ADMISSION_INVALID';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.snapshot_complete OR NEW.attempt <> owner.attempt
       OR NULLIF(current_setting('app.ingestion_job_id', true), '')::bigint IS DISTINCT FROM owner.id
       OR NULLIF(current_setting('app.ingestion_job_attempt', true), '')::integer IS DISTINCT FROM owner.attempt
       OR NOT (owner.status = 'running' OR (owner.status = 'succeeded' AND NEW.snapshot_complete)) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RESOURCE_SNAPSHOT_ATTEMPT_FENCED';
    END IF;
    IF NEW.candidate_set_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.documents_documentsetversion v WHERE v.id = NEW.candidate_set_version_id
        AND v.organization_id = NEW.organization_id AND v.document_set_id = owner.document_set_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RESOURCE_SNAPSHOT_CANDIDATE_SCOPE_INVALID';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER resource_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE
ON public.ingestion_resourcesnapshot FOR EACH ROW EXECUTE FUNCTION public.agenthub_resource_snapshot_guard();

CREATE FUNCTION public.agenthub_resource_snapshot_consistency() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE owner record; evidence record; target bigint;
BEGIN
    IF TG_TABLE_NAME = 'ingestion_resourcesnapshot' THEN target := NEW.job_id;
    ELSE target := NEW.id; END IF;
    SELECT * INTO owner FROM public.ingestion_stagedindexbuildjob WHERE id = target;
    IF NOT FOUND OR owner.kind <> 'mcp_resource_sync' THEN RETURN NULL; END IF;
    SELECT * INTO evidence FROM public.ingestion_resourcesnapshot WHERE job_id = target;
    IF NOT FOUND OR evidence.organization_id <> owner.organization_id OR evidence.attempt <> owner.attempt
       OR evidence.snapshot_complete IS DISTINCT FROM (owner.status = 'succeeded')
       OR (evidence.snapshot_complete AND
          (evidence.discovered_count <> evidence.changed_count + evidence.unchanged_count
           OR evidence.material_change IS DISTINCT FROM (evidence.candidate_set_version_id IS NOT NULL))) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RESOURCE_SNAPSHOT_PROJECTION_MISMATCH';
    END IF;
    RETURN NULL;
END
$body$;
CREATE CONSTRAINT TRIGGER resource_snapshot_consistency AFTER INSERT OR UPDATE
ON public.ingestion_resourcesnapshot DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.agenthub_resource_snapshot_consistency();
CREATE CONSTRAINT TRIGGER resource_job_consistency AFTER INSERT OR UPDATE
ON public.ingestion_stagedindexbuildjob DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.agenthub_resource_snapshot_consistency();

CREATE FUNCTION public.agenthub_resource_cursor_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE owner record;
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND
       (NEW.organization_id, NEW.source_id, NEW.external_id, NEW.external_id_hash, NEW.document_id)
       IS DISTINCT FROM (OLD.organization_id, OLD.source_id, OLD.external_id, OLD.external_id_hash, OLD.document_id)) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RESOURCE_CURSOR_LINEAGE_IMMUTABLE';
    END IF;
    SELECT * INTO owner FROM public.ingestion_stagedindexbuildjob j
    WHERE j.source_id = NEW.source_id AND j.kind = 'mcp_resource_sync' AND j.status = 'running'
    FOR SHARE;
    IF NOT FOUND OR owner.organization_id <> NEW.organization_id
       OR NULLIF(current_setting('app.ingestion_job_id', true), '')::bigint IS DISTINCT FROM owner.id
       OR NULLIF(current_setting('app.ingestion_job_attempt', true), '')::integer IS DISTINCT FROM owner.attempt THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RESOURCE_CURSOR_ATTEMPT_FENCED';
    END IF;
    IF NEW.state = 'active' AND (NEW.last_seen_job_id <> owner.id OR NEW.last_seen_attempt <> owner.attempt) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RESOURCE_CURSOR_SEEN_INVALID';
    END IF;
    IF NEW.external_id_hash <> encode(sha256(convert_to(NEW.external_id, 'UTF8')), 'hex')
       OR NOT EXISTS (SELECT 1 FROM public.documents_documentversion v
           JOIN public.documents_document d ON d.id = v.document_id
           WHERE v.id = NEW.document_version_id AND v.document_id = NEW.document_id
           AND v.organization_id = NEW.organization_id AND d.organization_id = NEW.organization_id
           AND d.source_id = NEW.source_id AND v.checksum = NEW.content_checksum)
       OR NOT EXISTS (SELECT 1 FROM public.ingestion_stagedindexbuildjob j
           WHERE j.id = NEW.last_seen_job_id AND j.source_id = NEW.source_id
           AND j.organization_id = NEW.organization_id AND NEW.last_seen_attempt > 0
           AND NEW.last_seen_attempt <= j.attempt) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RESOURCE_CURSOR_PROVENANCE_INVALID';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER resource_cursor_guard BEFORE INSERT OR UPDATE OR DELETE
ON public.ingestion_sourcedocumentcursor FOR EACH ROW EXECUTE FUNCTION public.agenthub_resource_cursor_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    lineage = _legacy_function("agenthub_ingestion_job_lineage")
    needle = "    IF NEW.kind = 'rest_sync' THEN"
    lineage = lineage.replace(needle, """
    IF NEW.kind = 'mcp_resource_sync' THEN
        IF src.connector_type <> 'mcp_resource' OR NEW.status <> 'dispatch_pending' OR NEW.attempt <> 0 THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'RESOURCE_JOB_ADMISSION_INVALID';
        END IF;
        RETURN NEW;
    END IF;
""" + needle, 1)
    projection = _legacy_function("agenthub_connector_job_projection").replace(
        "job.kind = 'index_build'", "job.kind IN ('index_build', 'mcp_resource_sync')", 1
    )
    schema_editor.execute(lineage + projection + SQL, params=None)
    for table in ("ingestion_resourcesnapshot", "ingestion_sourcedocumentcursor"):
        quoted = schema_editor.quote_name(table)
        schema_editor.execute(f"""
            ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {quoted}
            USING (public.agenthub_tenant_scope_contains(organization_id))
            WITH CHECK (public.agenthub_tenant_scope_contains(organization_id));
        """)


def reverse(apps, schema_editor):
    if apps.get_model("ingestion", "StagedIndexBuildJob").objects.using(schema_editor.connection.alias).filter(kind="mcp_resource_sync").exists():
        raise RuntimeError("RESOURCE_JOB_ROLLBACK_REQUIRES_EMPTY_HISTORY")
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(_legacy_function("agenthub_ingestion_job_lineage") + _legacy_function("agenthub_connector_job_projection"), params=None)
    schema_editor.execute("""
        DROP TRIGGER resource_job_consistency ON public.ingestion_stagedindexbuildjob;
        DROP TRIGGER resource_snapshot_consistency ON public.ingestion_resourcesnapshot;
        DROP FUNCTION public.agenthub_resource_snapshot_consistency();
        DROP TRIGGER resource_snapshot_guard ON public.ingestion_resourcesnapshot;
        DROP FUNCTION public.agenthub_resource_snapshot_guard();
        DROP TRIGGER resource_cursor_guard ON public.ingestion_sourcedocumentcursor;
        DROP FUNCTION public.agenthub_resource_cursor_guard();
    """)
    for table in ("ingestion_resourcesnapshot", "ingestion_sourcedocumentcursor"):
        quoted = schema_editor.quote_name(table)
        schema_editor.execute(f"""
            DROP POLICY tenant_isolation ON {quoted};
            ALTER TABLE {quoted} NO FORCE ROW LEVEL SECURITY;
            ALTER TABLE {quoted} DISABLE ROW LEVEL SECURITY;
        """)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0028_resource_snapshot_evidence")]
    operations = [migrations.RunPython(install, reverse)]
