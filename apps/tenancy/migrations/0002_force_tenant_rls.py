from django.db import migrations


_EXCLUDED_MODELS = frozenset(
    {
        "audit.auditevent",
        "identity.consumer",
        "identity.consumertoken",
        "observability.usageevent",
        "tenancy.organizationmembership",
    }
)

_LEGACY_RLS_TABLES = (
    "ingestion_confluencedocumentcursor",
    "ingestion_confluencesyncrun",
    "ingestion_connectorschedulepromotiontarget",
    "ingestion_connectorsyncschedule",
    "ingestion_restdocumentcursor",
    "ingestion_restpullcontract",
    "ingestion_restsyncrun",
    "ingestion_tenantconfluenceprofilegrant",
    "ingestion_tenantrestpullprofilegrant",
)


def _protected_tables(apps):
    tables = []
    for model in apps.get_models():
        if model._meta.label_lower in _EXCLUDED_MODELS:
            continue
        fields = {field.name: field for field in model._meta.local_fields}
        field = fields.get("organization") or fields.get("organization_id")
        if field is not None and not field.null and model._meta.managed:
            tables.append(model._meta.db_table)
    return sorted(set(tables))


def enable_tenant_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION agenthub_tenant_scope_contains(candidate bigint)
            RETURNS boolean
            LANGUAGE sql
            STABLE
            PARALLEL SAFE
            AS $function$
                SELECT candidate = ANY(
                    COALESCE(
                        string_to_array(
                            NULLIF(current_setting('app.tenant_scope', true), ''), ','
                        )::bigint[],
                        ARRAY[]::bigint[]
                    )
                )
            $function$
            """
        )
        cursor.execute(
            "REVOKE ALL ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM PUBLIC"
        )
        for table in _protected_tables(apps):
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
            cursor.execute(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"""
                CREATE POLICY tenant_isolation ON {quoted}
                USING (agenthub_tenant_scope_contains(organization_id))
                WITH CHECK (agenthub_tenant_scope_contains(organization_id))
                """
            )


def disable_tenant_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    protected = _protected_tables(apps)
    with schema_editor.connection.cursor() as cursor:
        for table in protected:
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
            cursor.execute(f"ALTER TABLE {quoted} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} DISABLE ROW LEVEL SECURITY")
        cursor.execute("DROP FUNCTION IF EXISTS agenthub_tenant_scope_contains(bigint)")
        for table in _LEGACY_RLS_TABLES:
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"""
                CREATE POLICY tenant_isolation ON {quoted}
                USING (
                    organization_id =
                    NULLIF(current_setting('app.tenant_id', true), '')::bigint
                )
                WITH CHECK (
                    organization_id =
                    NULLIF(current_setting('app.tenant_id', true), '')::bigint
                )
                """
            )


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0002_agentrunevent_organization"),
        ("artifacts", "0003_alter_artifactversion_type"),
        ("builder", "0002_artifactdraft"),
        ("catalog", "0002_scenario_organization"),
        ("documents", "0002_documentsetgrant_scenariodocumentsetbinding"),
        ("evaluations", "0002_evalcaseresult_organization"),
        ("gateway", "0002_idempotencyrecord_organization"),
        ("identity", "0003_direct_tenant_lineage"),
        ("ingestion", "0010_restore_source_document_set_constraint"),
        ("releases", "0003_direct_tenant_lineage"),
        ("tenancy", "0001_initial"),
        ("tools", "0002_toolinvocation_approvalrequest_and_more"),
        ("workflows", "0003_workflowrunevent_organization"),
    ]

    operations = [migrations.RunPython(enable_tenant_rls, disable_tenant_rls)]
