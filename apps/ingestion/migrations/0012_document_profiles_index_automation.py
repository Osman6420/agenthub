import django.db.models.deletion
from django.db import migrations, models


def enable_preparation_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = schema_editor.quote_name("ingestion_documentsetpreparationprofile")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
            USING (agenthub_tenant_scope_contains(organization_id))
            WITH CHECK (agenthub_tenant_scope_contains(organization_id))"""
        )


def disable_preparation_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = schema_editor.quote_name("ingestion_documentsetpreparationprofile")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("artifacts", "0005_alter_artifactversion_type"),
        ("documents", "0006_scenario_document_set_access"),
        ("ingestion", "0011_ingestionworkerheartbeat_stagedindexbuildjob_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="indexversion",
            name="chunking_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="chunked_index_versions",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="indexversion",
            name="retrieval_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="retrieval_index_versions",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="indexversion",
            name="summary_model_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="summarized_index_versions",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="indexversion",
            name="summary_prompt_contract",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="summary_prompt_index_versions",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="stagedindexbuildjob",
            name="chunking_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="index_build_jobs_as_chunking_profile",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="stagedindexbuildjob",
            name="retrieval_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="index_build_jobs_as_retrieval_profile",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="stagedindexbuildjob",
            name="summary_model_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="index_build_jobs_as_summary_model",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.AddField(
            model_name="stagedindexbuildjob",
            name="summary_prompt_contract",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="index_build_jobs_as_summary_prompt",
                to="artifacts.artifactversion",
            ),
        ),
        migrations.CreateModel(
            name="DocumentSetPreparationProfile",
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
                ("auto_prepare", models.BooleanField(default=False)),
                (
                    "chunking_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_preparation_chunking_profiles",
                        to="artifacts.artifactversion",
                    ),
                ),
                (
                    "document_set",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="preparation_profile",
                        to="documents.documentset",
                    ),
                ),
                (
                    "embedding_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_preparation_profiles",
                        to="ingestion.embeddingprofile",
                    ),
                ),
                (
                    "ocr_profile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_preparation_profiles",
                        to="ingestion.ocrprofile",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_preparation_profiles",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "retrieval_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_preparation_retrieval_profiles",
                        to="artifacts.artifactversion",
                    ),
                ),
                (
                    "summary_model_profile",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_preparation_summary_models",
                        to="artifacts.artifactversion",
                    ),
                ),
                (
                    "summary_prompt_contract",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_preparation_summary_prompts",
                        to="artifacts.artifactversion",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["organization", "auto_prepare"],
                        name="ingestion_d_organiz_603329_idx",
                    )
                ]
            },
        ),
        migrations.RunPython(enable_preparation_rls, disable_preparation_rls),
    ]
