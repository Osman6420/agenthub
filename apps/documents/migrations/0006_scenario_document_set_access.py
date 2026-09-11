import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


_TABLES = (
    "documents_scenariodocumentsetaccessrequest",
    "documents_scenariodocumentsetgrant",
)


def enable_access_rls(apps, schema_editor):
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


def disable_access_rls(apps, schema_editor):
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
        ("documents", "0005_public_ids_constrain"),
        ("identity", "0008_delegated_assignments"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScenarioDocumentSetAccessRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("purpose", models.CharField(max_length=500)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_reason", models.CharField(blank=True, max_length=500)),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="decided_scenario_document_set_access_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document_set",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scenario_access_requests",
                        to="documents.documentset",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scenario_document_set_access_requests",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scenario_document_set_access_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_set_access_requests",
                        to="catalog.scenario",
                    ),
                ),
            ],
            options={
                "ordering": ["organization_id", "-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "pending")),
                        fields=("scenario", "document_set"),
                        name="uniq_pending_scenario_document_set_request",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ScenarioDocumentSetGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "permission",
                    models.CharField(
                        choices=[("retrieve", "Retrieve")],
                        default="retrieve",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("granted", "Granted"), ("revoked", "Revoked")],
                        default="granted",
                        max_length=16,
                    ),
                ),
                ("granted_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "document_set",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scenario_grants",
                        to="documents.documentset",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="granted_scenario_document_set_access",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scenario_document_set_grants",
                        to="tenancy.organization",
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revoked_scenario_document_set_access",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_set_grants",
                        to="catalog.scenario",
                    ),
                ),
            ],
            options={
                "ordering": ["organization_id", "scenario_id", "document_set_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scenario", "document_set", "permission"),
                        name="uniq_scenario_document_set_grant",
                    )
                ],
            },
        ),
        migrations.RunPython(enable_access_rls, disable_access_rls),
    ]
