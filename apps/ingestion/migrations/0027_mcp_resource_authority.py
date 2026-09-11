"""Resource catalog immutability, exact source lineage and default-deny grants."""

from importlib import import_module

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION public.agenthub_connection_identity_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE profile record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'CONNECTION_IMMUTABLE';
    END IF;
    IF NEW.kind = 'rest_pull' THEN
        SELECT logical_id, revision INTO profile FROM public.ingestion_restpullprofile
        WHERE id = NEW.rest_profile_id FOR SHARE;
    ELSIF NEW.kind = 'confluence_dc' THEN
        SELECT logical_id, revision INTO profile FROM public.ingestion_confluenceprofile
        WHERE id = NEW.confluence_profile_id FOR SHARE;
    ELSIF NEW.kind = 'mcp_resource' THEN
        SELECT logical_id, revision INTO profile FROM public.ingestion_mcpresourceprofile
        WHERE id = NEW.mcp_resource_profile_id FOR SHARE;
    ELSE
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'CONNECTION_KIND_INVALID';
    END IF;
    IF NOT FOUND OR NEW.logical_id IS DISTINCT FROM profile.logical_id
       OR NEW.revision IS DISTINCT FROM profile.revision
       OR NEW.profile_checksum !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'CONNECTION_PROFILE_MISMATCH';
    END IF;
    RETURN NEW;
END
$body$;

CREATE FUNCTION public.agenthub_mcp_resource_profile_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND
       (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'MCP_RESOURCE_PROFILE_IMMUTABLE';
    END IF;
    IF NEW.status NOT IN ('active', 'disabled') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'MCP_RESOURCE_PROFILE_STATUS_INVALID';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER mcp_resource_profile_guard BEFORE INSERT OR UPDATE OR DELETE
ON public.ingestion_mcpresourceprofile FOR EACH ROW
EXECUTE FUNCTION public.agenthub_mcp_resource_profile_guard();

CREATE OR REPLACE FUNCTION public.agenthub_source_connection_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
DECLARE identity record;
BEGIN
    IF TG_OP = 'UPDATE' AND (NEW.connector_type = 'mcp_resource' OR OLD.connector_type = 'mcp_resource')
       AND (NEW.organization_id, NEW.connector_type, NEW.document_set_id, NEW.connection_id)
           IS DISTINCT FROM (OLD.organization_id, OLD.connector_type, OLD.document_set_id, OLD.connection_id) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'MCP_RESOURCE_SOURCE_BINDING_IMMUTABLE';
    END IF;
    IF NEW.connection_id IS NULL THEN
        IF TG_OP = 'UPDATE' AND OLD.connection_id IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SOURCE_CONNECTION_DOWNGRADE';
        END IF;
        IF NEW.connector_type = 'mcp_resource' THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SOURCE_CONNECTION_REQUIRED';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO identity FROM public.ingestion_connection WHERE id = NEW.connection_id;
    IF NOT FOUND OR NOT (
        (NEW.connector_type = 'generic_rest' AND identity.kind = 'rest_pull'
         AND NEW.rest_profile_id IS NOT DISTINCT FROM identity.rest_profile_id)
        OR (NEW.connector_type = 'confluence_dc' AND identity.kind = 'confluence_dc'
            AND NEW.confluence_profile_id IS NOT DISTINCT FROM identity.confluence_profile_id)
        OR (NEW.connector_type = 'mcp_resource' AND identity.kind = 'mcp_resource')
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'SOURCE_CONNECTION_MISMATCH';
    END IF;
    IF NEW.connector_type = 'mcp_resource' AND NOT EXISTS (
        SELECT 1 FROM public.documents_documentset d WHERE d.id = NEW.document_set_id
        AND d.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'MCP_RESOURCE_SOURCE_SCOPE_INVALID';
    END IF;
    RETURN NEW;
END
$body$;

CREATE FUNCTION public.agenthub_mcp_resource_grant_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $body$
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND
       (to_jsonb(NEW) - 'enabled') IS DISTINCT FROM (to_jsonb(OLD) - 'enabled')) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'MCP_RESOURCE_GRANT_IMMUTABLE';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.documents_documentset d
        WHERE d.id = NEW.document_set_id AND d.organization_id = NEW.organization_id) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'MCP_RESOURCE_GRANT_SCOPE_INVALID';
    END IF;
    RETURN NEW;
END
$body$;
CREATE TRIGGER mcp_resource_grant_guard BEFORE INSERT OR UPDATE OR DELETE
ON public.ingestion_tenantmcpresourcegrant FOR EACH ROW
EXECUTE FUNCTION public.agenthub_mcp_resource_grant_guard();
ALTER TABLE public.ingestion_tenantmcpresourcegrant ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingestion_tenantmcpresourcegrant FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON public.ingestion_tenantmcpresourcegrant
USING (public.agenthub_tenant_scope_contains(organization_id))
WITH CHECK (public.agenthub_tenant_scope_contains(organization_id));
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL, params=None)


def reverse(apps, schema_editor):
    # Reversing the schema must never silently discard a registered profile/grant.
    if apps.get_model("ingestion", "McpResourceProfile").objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError("MCP_RESOURCE_ROLLBACK_REQUIRES_EMPTY_CATALOG")
    if schema_editor.connection.vendor != "postgresql":
        return
    original = import_module("apps.ingestion.migrations.0021_connection_identity")._SQL
    for name in ("agenthub_connection_identity_guard", "agenthub_source_connection_guard"):
        function = "CREATE FUNCTION public." + name
        restored = function + original.split(function, 1)[1].split("$body$;", 1)[0] + "$body$;"
        schema_editor.execute(restored.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1), params=None)
    schema_editor.execute("""
        DROP TRIGGER mcp_resource_profile_guard ON public.ingestion_mcpresourceprofile;
        DROP FUNCTION public.agenthub_mcp_resource_profile_guard();
        DROP TRIGGER mcp_resource_grant_guard ON public.ingestion_tenantmcpresourcegrant;
        DROP FUNCTION public.agenthub_mcp_resource_grant_guard();
        DROP POLICY tenant_isolation ON public.ingestion_tenantmcpresourcegrant;
        ALTER TABLE public.ingestion_tenantmcpresourcegrant NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.ingestion_tenantmcpresourcegrant DISABLE ROW LEVEL SECURITY;
    """)


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0026_mcp_resource_catalog")]
    operations = [migrations.RunPython(install, reverse)]
