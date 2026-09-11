from django.db import migrations


_TABLE = "agents_agentruntimecontrol"


def split_runtime_control_policies(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quoted = schema_editor.quote_name(_TABLE)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
        cursor.execute(
            f"""CREATE POLICY runtime_control_select ON {quoted}
                FOR SELECT
                USING (
                    organization_id IS NULL
                    OR agenthub_tenant_scope_contains(organization_id)
                )"""
        )
        cursor.execute(
            f"""CREATE POLICY runtime_control_insert ON {quoted}
                FOR INSERT
                WITH CHECK (
                    agenthub_tenant_scope_contains(organization_id)
                    OR (
                        organization_id IS NULL
                        AND COALESCE(current_setting('app.tenant_scope', true), '') = ''
                    )
                )"""
        )
        cursor.execute(
            f"""CREATE POLICY runtime_control_update ON {quoted}
                FOR UPDATE
                USING (
                    agenthub_tenant_scope_contains(organization_id)
                    OR (
                        organization_id IS NULL
                        AND COALESCE(current_setting('app.tenant_scope', true), '') = ''
                    )
                )
                WITH CHECK (
                    agenthub_tenant_scope_contains(organization_id)
                    OR (
                        organization_id IS NULL
                        AND COALESCE(current_setting('app.tenant_scope', true), '') = ''
                    )
                )"""
        )


def restore_runtime_control_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quoted = schema_editor.quote_name(_TABLE)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS runtime_control_select ON {quoted}")
        cursor.execute(f"DROP POLICY IF EXISTS runtime_control_insert ON {quoted}")
        cursor.execute(f"DROP POLICY IF EXISTS runtime_control_update ON {quoted}")
        cursor.execute(
            f"""CREATE POLICY tenant_isolation ON {quoted}
                USING (
                    organization_id IS NULL
                    OR agenthub_tenant_scope_contains(organization_id)
                )
                WITH CHECK (
                    organization_id IS NULL
                    OR agenthub_tenant_scope_contains(organization_id)
                )"""
        )


class Migration(migrations.Migration):
    dependencies = [("agents", "0003_alter_agentrun_checkpoint_version_and_more")]

    operations = [
        migrations.RunPython(split_runtime_control_policies, restore_runtime_control_policy)
    ]
