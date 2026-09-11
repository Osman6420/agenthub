"""Preserve bounded publication target identifiers in immutable revision plans."""

from importlib import import_module

from django.db import migrations


def guard_sql():
    previous = import_module("apps.ingestion.migrations.0037_resource_source_revisions")
    sql = previous.guard_sql(resources=True)
    sql = sql.split("CREATE OR REPLACE FUNCTION public.agenthub_source_revision_family_guard")[0]
    sql = sql.replace(
        "ARRAY['interval_seconds','preparation']",
        "ARRAY['interval_seconds','preparation','publication_targets']",
    )
    return sql.replace(
        "    RETURN NEW;",
        """
    IF NEW.schedule_config ? 'publication_targets' THEN
        IF NOT (NEW.schedule_config ? 'preparation')
           OR jsonb_typeof(NEW.schedule_config->'publication_targets') <> 'array' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'SOURCE_REVISION_PUBLICATION_INVALID';
        END IF;
        IF jsonb_array_length(NEW.schedule_config->'publication_targets') NOT BETWEEN 1 AND 200
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                      NEW.schedule_config->'publication_targets') t
                      WHERE jsonb_typeof(t) <> 'number'
                         OR t::text !~ '^[1-9][0-9]{0,18}$') THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'SOURCE_REVISION_PUBLICATION_INVALID';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(
                   NEW.schedule_config->'publication_targets') t
                   WHERE t::numeric > 9223372036854775807)
           OR (SELECT count(DISTINCT t) FROM jsonb_array_elements_text(
                 NEW.schedule_config->'publication_targets') t)
              <> jsonb_array_length(NEW.schedule_config->'publication_targets') THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'SOURCE_REVISION_PUBLICATION_INVALID';
        END IF;
    END IF;
    RETURN NEW;""",
    )


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(guard_sql(), params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            role = cursor.fetchone()
        if not role or not role[0]:
            raise RuntimeError("REVISION_PUBLICATION_ROLLBACK_REQUIRES_PRIVILEGED_ROLE")
    if (
        apps.get_model("ingestion", "SourceConfigurationRevision")
        .objects.using(schema_editor.connection.alias)
        .filter(schedule_config__has_key="publication_targets")
        .exists()
    ):
        raise RuntimeError("REVISION_PUBLICATION_ROLLBACK_REQUIRES_EMPTY_HISTORY")
    if schema_editor.connection.vendor == "postgresql":
        previous = import_module("apps.ingestion.migrations.0037_resource_source_revisions")
        schema_editor.execute(previous.guard_sql(resources=True), params=None)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0040_retained_parent_guard")]
    operations = [migrations.RunPython(install, reverse)]
