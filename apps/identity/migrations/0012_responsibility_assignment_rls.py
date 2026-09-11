from django.db import migrations


_TABLES = (
    "identity_organizationresponsibilityassignment",
    "identity_projectresponsibilityassignment",
    "identity_scenarioresponsibilityassignment",
    "identity_documentsetresponsibilityassignment",
)


def enable_responsibility_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in _TABLES:
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY")
            cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
            cursor.execute(
                f"""
                CREATE POLICY tenant_isolation ON {quoted}
                USING (agenthub_tenant_scope_contains(organization_id))
                WITH CHECK (agenthub_tenant_scope_contains(organization_id))
                """
            )


def disable_responsibility_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in _TABLES:
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
            cursor.execute(f"ALTER TABLE {quoted} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0011_remove_globaladministrator_user_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_responsibility_rls, disable_responsibility_rls),
    ]
