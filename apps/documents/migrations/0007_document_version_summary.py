import django.db.models.deletion
from django.db import migrations, models


def enable_summary_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = schema_editor.quote_name("documents_documentversionsummary")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
            USING (agenthub_tenant_scope_contains(organization_id))
            WITH CHECK (agenthub_tenant_scope_contains(organization_id))"""
        )


def disable_summary_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = schema_editor.quote_name("documents_documentversionsummary")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("artifacts", "0005_alter_artifactversion_type"),
        ("documents", "0006_scenario_document_set_access"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentVersionSummary",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("content", models.TextField(blank=True)),
                ("checksum", models.CharField(blank=True, max_length=64)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("input_checksum", models.CharField(max_length=64)),
                (
                    "document_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="summaries",
                        to="documents.documentversion",
                    ),
                ),
                (
                    "model_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_summaries_as_model",
                        to="artifacts.artifactversion",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_version_summaries",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "prompt_contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_summaries_as_prompt",
                        to="artifacts.artifactversion",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["organization", "status"],
                        name="documents_d_organiz_94e529_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("document_version", "model_profile", "prompt_contract"),
                        name="uniq_document_summary_provenance",
                    )
                ],
            },
        ),
        migrations.RunPython(enable_summary_rls, disable_summary_rls),
    ]
