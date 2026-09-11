"""Serialize late evaluation and selected-set references with retirement."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION public.agenthub_retained_selection_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE selected_id bigint; generation record;
BEGIN
    IF TG_TABLE_NAME = 'documents_documentsetversion' THEN
        selected_id := NEW.built_index_version_id;
    ELSE
        selected_id := NEW.index_version_id;
    END IF;
    IF selected_id IS NULL THEN RETURN NEW; END IF;
    SELECT * INTO generation FROM public.ingestion_indexversion
    WHERE id = selected_id FOR SHARE;
    IF NOT FOUND OR generation.organization_id <> NEW.organization_id
       OR generation.storage_state = 'retired' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'GENERATION_SELECTION_UNAVAILABLE';
    END IF;
    IF TG_TABLE_NAME = 'documents_documentsetversion' THEN
        IF generation.document_set_version_id IS DISTINCT FROM NEW.id THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'GENERATION_SELECTION_SCOPE';
        END IF;
    ELSE
        IF generation.document_set_version_id IS DISTINCT FROM NEW.document_set_version_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'GENERATION_SELECTION_SCOPE';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retained_selection_guard BEFORE INSERT OR UPDATE
ON public.documents_documentsetversion FOR EACH ROW
EXECUTE FUNCTION public.agenthub_retained_selection_guard();
CREATE TRIGGER retained_selection_guard BEFORE INSERT OR UPDATE
ON public.evaluations_questionevaluationrun FOR EACH ROW
EXECUTE FUNCTION public.agenthub_retained_selection_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER retained_selection_guard ON public.documents_documentsetversion;
            DROP TRIGGER retained_selection_guard ON public.evaluations_questionevaluationrun;
            DROP FUNCTION public.agenthub_retained_selection_guard();
        """)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0041_revision_publication_schedule")]
    operations = [migrations.RunPython(install, reverse)]
