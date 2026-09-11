"""Extend immutable source families with exact typed snapshot preparation evidence."""

from importlib import import_module

from django.db import migrations


def guard_sql(*, resources):
    previous = import_module("apps.ingestion.migrations.0033_source_configuration_revision").SQL
    scope = previous.split("CREATE TRIGGER source_revision_guard")[0]
    family = previous[
        previous.index("CREATE FUNCTION public.agenthub_source_revision_family_guard") :
    ]
    family = family.split("CREATE CONSTRAINT TRIGGER source_revision_family_guard")[0]
    if resources:
        scope = scope.replace(
            "root.connector_type <> 'generic_rest'\n       OR item.connector_type <> 'generic_rest'"
            " OR root.document_set_id <> item.document_set_id",
            "root.connector_type NOT IN ('generic_rest', 'confluence_dc', 'mcp_resource')\n"
            "       OR item.connector_type IS DISTINCT FROM root.connector_type\n"
            "       OR root.document_set_id IS NULL\n"
            "       OR root.document_set_id IS DISTINCT FROM item.document_set_id",
        )
        family = family.replace(
            "JOIN public.ingestion_restsyncrun r ON r.id = j.rest_sync_run_id",
            "LEFT JOIN public.ingestion_restsyncrun r ON r.id = j.rest_sync_run_id\n"
            "            LEFT JOIN public.ingestion_confluencesyncrun c"
            " ON c.id = j.confluence_sync_run_id\n"
            "            LEFT JOIN public.ingestion_resourcesnapshot m ON m.job_id = j.id",
        ).replace(
            "AND r.snapshot_complete AND r.status = 'succeeded' AND b.status = 'succeeded'\n"
            "              AND r.candidate_set_version_id = b.document_set_version_id",
            """AND b.status = 'succeeded' AND b.organization_id = NEW.organization_id
              AND i.organization_id = NEW.organization_id
              AND (
                (j.kind = 'rest_sync' AND r.organization_id = NEW.organization_id
                 AND r.source_id = NEW.source_id AND r.snapshot_complete AND r.status = 'succeeded'
                 AND r.candidate_set_version_id = b.document_set_version_id)
                OR (j.kind = 'confluence_sync' AND c.organization_id = NEW.organization_id
                 AND c.source_id = NEW.source_id AND c.snapshot_complete AND c.status = 'succeeded'
                 AND c.candidate_set_version_id = b.document_set_version_id)
                OR (j.kind = 'mcp_resource_sync' AND m.organization_id = NEW.organization_id
                 AND m.snapshot_complete AND m.attempt = j.attempt
                 AND m.candidate_set_version_id = b.document_set_version_id)
              )""",
        )
    return (scope + family).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(guard_sql(resources=True), params=None)
        schema_editor.execute(writer_sql(families=True), params=None)


def writer_sql(*, families):
    previous = import_module("apps.ingestion.migrations.0023_ingestion_job_authority").FORWARD
    sql = previous[previous.index("CREATE FUNCTION public.agenthub_connector_source_writer") :]
    sql = sql.split("CREATE TRIGGER rest_source_writer")[0]
    if families:
        sql = sql.replace(
            "    RETURN NEW;",
            """
    IF EXISTS (SELECT 1 FROM public.ingestion_sourceconfigurationrevision
               WHERE source_id = NEW.source_id) AND EXISTS (
        WITH family AS (
            SELECT r.source_id FROM public.ingestion_sourceconfigurationrevision r
            JOIN public.ingestion_sourceconfigurationrevision base
              ON base.root_source_id = r.root_source_id
            WHERE base.source_id = NEW.source_id AND r.organization_id = NEW.organization_id
        )
        SELECT 1 FROM public.ingestion_stagedindexbuildjob j
        WHERE j.source_id IN (SELECT source_id FROM family)
          AND j.status IN ('dispatch_pending','queued','running','retry_wait',
                           'reconciliation_required')
        UNION ALL
        SELECT 1 FROM public.ingestion_restsyncrun r
        WHERE r.source_id IN (SELECT source_id FROM family)
          AND r.status IN ('queued','running','retry')
        UNION ALL
        SELECT 1 FROM public.ingestion_confluencesyncrun c
        WHERE c.source_id IN (SELECT source_id FROM family)
          AND c.status IN ('queued','running','retry')
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SOURCE_BUSY';
    END IF;
    RETURN NEW;
""",
        )
    return sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            role = cursor.fetchone()
        if not role or not role[0]:
            raise RuntimeError("SOURCE_REVISION_ROLLBACK_REQUIRES_PRIVILEGED_ROLE")
    if (
        apps.get_model("ingestion", "SourceConfigurationRevision")
        .objects.using(schema_editor.connection.alias)
        .exclude(source__connector_type="generic_rest")
        .exists()
    ):
        raise RuntimeError("SOURCE_REVISION_ROLLBACK_REQUIRES_EMPTY_RESOURCE_HISTORY")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(guard_sql(resources=False), params=None)
        schema_editor.execute(writer_sql(families=False), params=None)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0036_rest_setup_retention")]
    operations = [migrations.RunPython(install, reverse)]
