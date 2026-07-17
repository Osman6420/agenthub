import django.db.models.deletion
from django.db import migrations, models


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in ("tools_mcpcatalogsource", "tools_mcpcatalogcandidate"):
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"""CREATE POLICY tenant_isolation ON {quoted}
                USING (agenthub_tenant_scope_contains(organization_id))
                WITH CHECK (agenthub_tenant_scope_contains(organization_id))"""
            )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in ("tools_mcpcatalogcandidate", "tools_mcpcatalogsource"):
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
            cursor.execute(f"ALTER TABLE {quoted} NO FORCE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0002_force_tenant_rls"),
        ("tools", "0002_toolinvocation_approvalrequest_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="McpCatalogSource",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=128)),
                ("destination", models.JSONField()),
                ("secret_ref", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("disabled", "Disabled")],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("generation", models.PositiveIntegerField(default=0)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mcp_catalog_sources",
                        to="tenancy.organization",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="McpCatalogCandidate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("remote_name", models.CharField(max_length=128)),
                ("description", models.CharField(blank=True, max_length=1000)),
                ("input_schema", models.JSONField()),
                ("metadata_checksum", models.CharField(max_length=64)),
                ("source_destination_checksum", models.CharField(max_length=64)),
                ("generation", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("quarantined", "Quarantined"),
                            ("registered", "Registered"),
                            ("drifted", "Drifted"),
                            ("missing", "Missing"),
                            ("rejected", "Rejected"),
                        ],
                        default="quarantined",
                        max_length=16,
                    ),
                ),
                ("reviewed_by", models.CharField(blank=True, max_length=200)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mcp_catalog_candidates",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "registered_definition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="catalog_candidates",
                        to="tools.tooldefinition",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="candidates",
                        to="tools.mcpcatalogsource",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="mcpcatalogsource",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"), name="uniq_mcp_catalog_source_org_name"
            ),
        ),
        migrations.AddIndex(
            model_name="mcpcatalogcandidate",
            index=models.Index(
                fields=["organization", "source", "status"], name="tools_mcpca_organiz_69f0ec_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="mcpcatalogcandidate",
            constraint=models.UniqueConstraint(
                fields=("source", "remote_name", "metadata_checksum"),
                name="uniq_mcp_candidate_source_name_checksum",
            ),
        ),
        migrations.RunPython(enable_rls, disable_rls),
    ]
