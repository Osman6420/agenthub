"""Serialize new lineage references with shared-generation retirement."""

from django.db import migrations

FORWARD = r"""
CREATE FUNCTION public.agenthub_retained_parent_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE parent record;
BEGIN
    IF NEW.parent_index_version_id IS NULL THEN RETURN NEW; END IF;
    IF TG_OP = 'UPDATE' AND NEW.parent_index_version_id = OLD.parent_index_version_id
       AND NEW.organization_id = OLD.organization_id THEN RETURN NEW; END IF;
    SELECT * INTO parent FROM public.ingestion_indexversion
    WHERE id = NEW.parent_index_version_id FOR SHARE;
    IF NOT FOUND OR parent.organization_id <> NEW.organization_id
       OR parent.storage_state = 'retired' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'GENERATION_PARENT_UNAVAILABLE';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retained_parent_guard BEFORE INSERT OR UPDATE
ON public.ingestion_indexversion FOR EACH ROW
EXECUTE FUNCTION public.agenthub_retained_parent_guard();
"""

REVERSE = """
DROP TRIGGER retained_parent_guard ON public.ingestion_indexversion;
DROP FUNCTION public.agenthub_retained_parent_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0039_shared_vector_retention")]
    operations = [migrations.RunPython(install, reverse)]
