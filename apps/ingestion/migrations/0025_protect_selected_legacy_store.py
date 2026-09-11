"""Protect retained selections inside the existing least-privilege DDL authority."""

from importlib import import_module

from django.db import migrations

FORWARD = r"""
CREATE OR REPLACE FUNCTION public.agenthub_drop_index_store(candidate_index_id bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $function$
DECLARE target record; relation_name text;
BEGIN
    IF candidate_index_id IS NULL OR candidate_index_id < 1 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'INDEX_STORE_ID_INVALID';
    END IF;
    SELECT organization_id, status, storage_layout INTO target
    FROM public.ingestion_indexversion
    WHERE id = candidate_index_id AND public.agenthub_tenant_scope_contains(organization_id)
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'INDEX_STORE_SCOPE_DENIED';
    END IF;
    IF target.storage_layout <> 'legacy' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INDEX_STORE_LAYOUT_INVALID';
    END IF;
    IF EXISTS (SELECT 1 FROM public.workflows_runretrievalgeneration
        WHERE index_version_id = candidate_index_id AND organization_id = target.organization_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RETRIEVAL_GENERATION_PROTECTED';
    END IF;
    IF target.status = 'active' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INDEX_STORE_ACTIVE';
    END IF;
    relation_name := 'chunk_iv_' || candidate_index_id::text;
    EXECUTE pg_catalog.format('DROP TABLE IF EXISTS public.%I', relation_name);
    -- A receipt blocked behind this lock must observe an unreadable generation.
    UPDATE public.ingestion_indexversion SET store_ready = false WHERE id = candidate_index_id;
END
$function$;
REVOKE ALL ON FUNCTION public.agenthub_drop_index_store(bigint) FROM PUBLIC;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD, params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        previous = import_module("apps.ingestion.migrations.0015_index_store_ddl_functions")
        schema_editor.execute(previous._DROP_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0024_connector_completion_outbox"),
        ("workflows", "0020_durable_retrieval_selection"),
    ]
    operations = [migrations.RunPython(install, reverse)]
