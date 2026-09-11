"""Keep immutable workflow locking inside the checked revision trigger."""

from django.db import migrations


def apply(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        # PostgreSQL row locks require UPDATE privilege. Only this trigger needs
        # the lock: it validates every source/snapshot scope and returns NEW,
        # writes no other rows, and insertion still passes the table's FORCE RLS.
        # Its static SQL already qualifies every application table with public.
        schema_editor.execute("""
            CREATE FUNCTION public.agenthub_revision_lock_scope() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog AS $$
            BEGIN
                -- Runs as the caller before the definer trigger takes any lock.
                IF NOT public.agenthub_tenant_scope_contains(NEW.organization_id)
                   OR NOT EXISTS (
                       SELECT 1 FROM public.workflows_workflowversion w
                       WHERE w.id = NEW.workflow_version_id
                         AND w.organization_id = NEW.organization_id
                         AND w.scenario_id = NEW.scenario_id
                   ) THEN
                    RAISE EXCEPTION 'SCENARIO_REVISION_SCOPE_INVALID' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END $$;
            REVOKE ALL ON FUNCTION public.agenthub_revision_lock_scope() FROM PUBLIC;
            CREATE TRIGGER scenario_revision_00_lock_scope BEFORE INSERT
                ON public.releases_scenariorevision FOR EACH ROW
                EXECUTE FUNCTION public.agenthub_revision_lock_scope();
            ALTER FUNCTION public.agenthub_revision_integrity() SECURITY DEFINER;
            ALTER FUNCTION public.agenthub_revision_integrity() SET search_path = pg_catalog;
            REVOKE ALL ON FUNCTION public.agenthub_revision_integrity() FROM PUBLIC;
        """)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER scenario_revision_00_lock_scope ON public.releases_scenariorevision;
            DROP FUNCTION public.agenthub_revision_lock_scope();
            ALTER FUNCTION public.agenthub_revision_integrity() SECURITY INVOKER;
            ALTER FUNCTION public.agenthub_revision_integrity()
                SET search_path = pg_catalog, public;
            GRANT EXECUTE ON FUNCTION public.agenthub_revision_integrity() TO PUBLIC;
        """)


class Migration(migrations.Migration):
    dependencies = [("releases", "0007_source_publication")]
    operations = [migrations.RunPython(apply, reverse)]
