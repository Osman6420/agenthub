"""Allow reviewed resource publication through the shared durable publication path."""

from importlib import import_module

from django.db import migrations


def guard_sql(*, publication):
    previous = import_module("apps.ingestion.migrations.0032_resource_snapshot_schedule")
    sql = previous.SCHEDULE_SQL.split("CREATE TRIGGER", 1)[0]
    sql = sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if publication:
        sql = sql.replace(
            "('draft_only', 'stage_only')",
            "('draft_only', 'stage_only', 'promote_if_safe')"
            " OR (NEW.automation_mode = 'promote_if_safe' AND "
            "(NEW.promotion_approved_by = '' OR NEW.embedding_profile_id IS NULL))",
        )
    return sql


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(guard_sql(publication=True), params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            role = cursor.fetchone()
        if not role or not role[0]:
            raise RuntimeError("RESOURCE_PUBLICATION_ROLLBACK_REQUIRES_PRIVILEGED_ROLE")
    alias = schema_editor.connection.alias
    if (
        apps.get_model("ingestion", "ConnectorSyncSchedule")
        .objects.using(alias)
        .filter(source__connector_type="mcp_resource", automation_mode="promote_if_safe")
        .exists()
        or apps.get_model("releases", "ScenarioPublication")
        .objects.using(alias)
        .filter(source_job__source__connector_type="mcp_resource")
        .exists()
    ):
        raise RuntimeError("RESOURCE_PUBLICATION_ROLLBACK_REQUIRES_EMPTY_HISTORY")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(guard_sql(publication=False), params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0037_resource_source_revisions"),
        ("releases", "0007_source_publication"),
    ]
    operations = [migrations.RunPython(install, reverse)]
