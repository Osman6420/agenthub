from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def _set_tenant_scope(schema_editor, organization_id: int) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(organization_id)])


def backfill_owner_memberships(apps, schema_editor) -> None:
    AIProject = apps.get_model("catalog", "AIProject")
    Organization = apps.get_model("tenancy", "Organization")
    OrganizationMembership = apps.get_model("tenancy", "OrganizationMembership")
    alias = schema_editor.connection.alias
    organization_ids = Organization.objects.using(alias).values_list("pk", flat=True).iterator()
    for organization_id in organization_ids:
        _set_tenant_scope(schema_editor, organization_id)
        projects = (
            AIProject.objects.using(alias)
            .filter(organization_id=organization_id)
            .exclude(owner="")
            .iterator()
        )
        for project in projects:
            membership = (
                OrganizationMembership.objects.using(alias)
                .filter(organization_id=organization_id, user__username=project.owner)
                .only("pk")
                .first()
            )
            if membership is not None:
                AIProject.objects.using(alias).filter(pk=project.pk).update(
                    owner_membership_id=membership.pk
                )


def clear_owner_memberships(apps, schema_editor) -> None:
    AIProject = apps.get_model("catalog", "AIProject")
    Organization = apps.get_model("tenancy", "Organization")
    alias = schema_editor.connection.alias
    organization_ids = Organization.objects.using(alias).values_list("pk", flat=True).iterator()
    for organization_id in organization_ids:
        _set_tenant_scope(schema_editor, organization_id)
        AIProject.objects.using(alias).filter(organization_id=organization_id).update(
            owner_membership_id=None
        )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0005_public_ids_constrain"),
        ("tenancy", "0002_force_tenant_rls"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiproject",
            name="owner_membership",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="owned_projects",
                to="tenancy.organizationmembership",
            ),
        ),
        migrations.RunPython(backfill_owner_memberships, clear_owner_memberships),
    ]
