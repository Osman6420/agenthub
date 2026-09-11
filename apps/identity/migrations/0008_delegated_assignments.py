import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


_TABLES = (
    "identity_projectadministratorassignment",
    "identity_scenarioeditorassignment",
    "identity_documentsetmanagerassignment",
)


def enable_assignment_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in _TABLES:
            quoted = schema_editor.quote_name(table)
            cursor.execute(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"""
                CREATE POLICY tenant_isolation ON {quoted}
                USING (agenthub_tenant_scope_contains(organization_id))
                WITH CHECK (agenthub_tenant_scope_contains(organization_id))
                """
            )


def disable_assignment_rls(apps, schema_editor):
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
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0006_aiproject_owner_membership"),
        ("documents", "0005_public_ids_constrain"),
        ("identity", "0007_globaladministrator"),
        ("tenancy", "0003_document_manager_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectAdministratorAssignment",
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
                    "assigned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_project_administrator_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_administrator_assignments",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="administrator_assignments",
                        to="catalog.aiproject",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_administrator_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["organization_id", "project_id", "user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("project", "user"),
                        name="uniq_project_administrator_assignment",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ScenarioEditorAssignment",
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
                    "assigned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_scenario_editor_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scenario_editor_assignments",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="editor_assignments",
                        to="catalog.scenario",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scenario_editor_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["organization_id", "scenario_id", "user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scenario", "user"),
                        name="uniq_scenario_editor_assignment",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="DocumentSetManagerAssignment",
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
                    "assigned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_document_set_manager_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document_set",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="manager_assignments",
                        to="documents.documentset",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_set_manager_assignments",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_set_manager_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["organization_id", "document_set_id", "user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("document_set", "user"),
                        name="uniq_document_set_manager_assignment",
                    )
                ],
            },
        ),
        migrations.RunPython(enable_assignment_rls, disable_assignment_rls),
    ]
