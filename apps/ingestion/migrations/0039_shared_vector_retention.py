"""Owner-only retirement of old, unreferenced shared generations."""

from importlib import import_module

from django.db import migrations

REFERENCES = r"""
CREATE FUNCTION public.agenthub_shared_retention_blocked(p_index bigint)
RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
 SELECT NOT EXISTS (SELECT 1 FROM public.ingestion_indexversion WHERE id = p_index)
 OR EXISTS (
   SELECT 1 FROM public.ingestion_indexversion i WHERE i.id = p_index AND (
     i.status IN ('active', 'building')
     OR EXISTS (SELECT 1 FROM public.releases_scenariorelease r
                WHERE r.organization_id = i.organization_id AND (
                  r.manifest->'index_versions' @> jsonb_build_array(i.id)
                  OR r.manifest->'document_set_versions'
                     @> jsonb_build_array(i.document_set_version_id)))
     OR EXISTS (SELECT 1 FROM public.evaluations_evaldatageneration e
                WHERE e.index_version_id = i.id)
     OR EXISTS (SELECT 1 FROM public.workflows_runretrievalgeneration g
                WHERE g.index_version_id = i.id)
     OR EXISTS (SELECT 1 FROM public.evaluations_questionevaluationrun e
                WHERE e.index_version_id = i.id)
     OR EXISTS (SELECT 1 FROM public.documents_documentsetversion v
                WHERE v.built_index_version_id = i.id)
     OR EXISTS (SELECT 1 FROM public.ingestion_indexversion child
                WHERE child.parent_index_version_id = i.id)
     OR EXISTS (SELECT 1 FROM public.ingestion_stagedindexbuildjob src
                JOIN public.ingestion_stagedindexbuildjob prep ON prep.id = src.preparation_job_id
                WHERE prep.result_index_version_id = i.id)
     OR EXISTS (SELECT 1 FROM public.ingestion_stagedindexbuildjob j
                WHERE (j.id = i.build_request_id
                       OR j.document_set_version_id = i.document_set_version_id)
                  AND j.status IN ('dispatch_pending','queued','running','retry_wait',
                                   'reconciliation_required'))
   )
 );
$$;
"""


def generation_guard(*, retention):
    previous = import_module("apps.ingestion.migrations.0018_shared_vector_integrity")._INTEGRITY
    sql = previous[previous.index("CREATE FUNCTION public.agenthub_shared_generation_integrity") :]
    sql = sql.split("CREATE TRIGGER", 1)[0].replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )
    if retention:
        sql = sql.replace(
            "OR (OLD.storage_state = 'open' AND NEW.storage_state IN ('sealed', 'retired'))",
            """OR (OLD.storage_state = 'open' AND NEW.storage_state IN ('sealed', 'retired'))
            OR (OLD.storage_state = 'sealed' AND NEW.storage_state = 'retired'
                AND current_setting('app.shared_vector_retention', true) = 'on'
                AND EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
                            WHERE c.oid = 'public.ingestion_sharedvectorchunk'::regclass
                              AND r.rolname = current_user)
                AND OLD.updated_at <= CURRENT_TIMESTAMP - interval '90 days'
                AND NOT public.agenthub_shared_retention_blocked(OLD.id))""",
        )
    return sql


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REFERENCES + generation_guard(retention=True), params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            role = cursor.fetchone()
        if not role or not role[0]:
            raise RuntimeError("SHARED_RETENTION_ROLLBACK_REQUIRES_PRIVILEGED_ROLE")
    if (
        apps.get_model("ingestion", "IndexVersion")
        .objects.using(schema_editor.connection.alias)
        .filter(storage_layout="shared_v1", storage_state="retired")
        .exists()
    ):
        raise RuntimeError("SHARED_RETENTION_ROLLBACK_REQUIRES_EMPTY_HISTORY")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            generation_guard(retention=False)
            + "DROP FUNCTION public.agenthub_shared_retention_blocked(bigint);",
            params=None,
        )


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0038_resource_publication_schedule")]
    operations = [migrations.RunPython(install, reverse)]
