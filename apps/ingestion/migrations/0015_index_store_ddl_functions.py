"""Install least-privilege DDL seams for per-IndexVersion pgvector stores.

The runtime application role deliberately has no schema CREATE privilege. These migration-owner
functions accept only an integer IndexVersion identity, re-resolve its tenant and lifecycle under
the caller's transaction-local scope, and emit DDL from fixed templates. PUBLIC receives no access;
deployment grants EXECUTE only to the application role.

Rollout: migrate before starting contract-revision-3 ingestion workers. Existing stores are not
touched. Rollback: stop/revert those workers first, then reverse this migration; store tables and
their data remain intact.
"""

from django.db import migrations


_PROVISION_SQL = r"""
CREATE OR REPLACE FUNCTION public.agenthub_provision_index_store(candidate_index_id bigint)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    target record;
    relation_name text;
    vector_type text;
    vector_opclass text;
    caller_role name := session_user;
BEGIN
    IF candidate_index_id IS NULL OR candidate_index_id < 1 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'INDEX_STORE_ID_INVALID';
    END IF;

    SELECT organization_id, dimensions, index_type, status
      INTO target
      FROM public.ingestion_indexversion
     WHERE id = candidate_index_id
       AND public.agenthub_tenant_scope_contains(organization_id);
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'INDEX_STORE_SCOPE_DENIED';
    END IF;
    IF target.status <> 'building' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INDEX_STORE_NOT_BUILDING';
    END IF;

    IF target.index_type = 'halfvec' AND target.dimensions BETWEEN 1 AND 4000 THEN
        vector_type := pg_catalog.format('public.halfvec(%s)', target.dimensions);
        vector_opclass := 'public.halfvec_cosine_ops';
    ELSIF target.index_type IN ('', 'vector') AND target.dimensions BETWEEN 1 AND 2000 THEN
        vector_type := pg_catalog.format('public.vector(%s)', target.dimensions);
        vector_opclass := 'public.vector_cosine_ops';
    ELSE
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'INDEX_STORE_GEOMETRY_INVALID';
    END IF;

    relation_name := 'chunk_iv_' || candidate_index_id::text;
    EXECUTE pg_catalog.format(
        'CREATE TABLE IF NOT EXISTS public.%I ('
        'id bigserial PRIMARY KEY, '
        'organization_id bigint NOT NULL, '
        'document_version_id bigint, '
        'ordinal integer NOT NULL, '
        'text text NOT NULL, '
        'chunk_kind varchar(16) NOT NULL DEFAULT ''content'', '
        'embedding %s NOT NULL)',
        relation_name,
        vector_type
    );
    EXECUTE pg_catalog.format(
        'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
        'chunk_kind varchar(16) NOT NULL DEFAULT ''content''',
        relation_name
    );
    EXECUTE pg_catalog.format(
        'CREATE INDEX IF NOT EXISTS %I ON public.%I '
        'USING hnsw (embedding %s) WITH (m = 16, ef_construction = 64)',
        relation_name || '_hnsw',
        relation_name,
        vector_opclass
    );
    EXECUTE pg_catalog.format(
        'CREATE INDEX IF NOT EXISTS %I ON public.%I '
        'USING gin (pg_catalog.to_tsvector(''simple'', text))',
        relation_name || '_fts',
        relation_name
    );
    EXECUTE pg_catalog.format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', relation_name);
    EXECUTE pg_catalog.format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', relation_name);
    EXECUTE pg_catalog.format('DROP POLICY IF EXISTS %I ON public.%I', relation_name || '_tenant', relation_name);
    EXECUTE pg_catalog.format(
        'CREATE POLICY %I ON public.%I '
        'USING (public.agenthub_tenant_scope_contains(organization_id)) '
        'WITH CHECK (public.agenthub_tenant_scope_contains(organization_id))',
        relation_name || '_tenant',
        relation_name
    );
    -- The function owner retains DDL ownership. The directly authenticated runtime role receives
    -- only the row/sequence privileges required by write/search; ownership, UPDATE, DELETE and
    -- schema CREATE are deliberately withheld. In production session_user is the application
    -- login, not a broker/header-derived value.
    EXECUTE pg_catalog.format(
        'GRANT SELECT, INSERT ON TABLE public.%I TO %I', relation_name, caller_role
    );
    EXECUTE pg_catalog.format(
        'GRANT USAGE, SELECT ON SEQUENCE public.%I TO %I',
        relation_name || '_id_seq',
        caller_role
    );
    RETURN relation_name;
END
$function$;
REVOKE ALL ON FUNCTION public.agenthub_provision_index_store(bigint) FROM PUBLIC;
"""


_DROP_SQL = r"""
CREATE OR REPLACE FUNCTION public.agenthub_drop_index_store(candidate_index_id bigint)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    target record;
    relation_name text;
BEGIN
    IF candidate_index_id IS NULL OR candidate_index_id < 1 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'INDEX_STORE_ID_INVALID';
    END IF;

    SELECT organization_id, status
      INTO target
      FROM public.ingestion_indexversion
     WHERE id = candidate_index_id
       AND public.agenthub_tenant_scope_contains(organization_id);
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'INDEX_STORE_SCOPE_DENIED';
    END IF;
    IF target.status = 'active' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'INDEX_STORE_ACTIVE';
    END IF;

    relation_name := 'chunk_iv_' || candidate_index_id::text;
    EXECUTE pg_catalog.format('DROP TABLE IF EXISTS public.%I', relation_name);
END
$function$;
REVOKE ALL ON FUNCTION public.agenthub_drop_index_store(bigint) FROM PUBLIC;
"""


def install_index_store_functions(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(_PROVISION_SQL)
        cursor.execute(_DROP_SQL)


def remove_index_store_functions(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP FUNCTION IF EXISTS public.agenthub_drop_index_store(bigint)"
        )
        cursor.execute(
            "DROP FUNCTION IF EXISTS public.agenthub_provision_index_store(bigint)"
        )


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0014_deprecate_document_set_retrieval_ownership")]

    operations = [
        migrations.RunPython(install_index_store_functions, remove_index_store_functions)
    ]
