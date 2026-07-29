import django.db.models.deletion
from django.db import migrations, models


def migrate_existing_controls(apps, schema_editor):
    control = apps.get_model("agents", "AgentRuntimeControl")
    control.objects.filter(organization__isnull=True).update(scope_type="platform")
    control.objects.filter(organization__isnull=False).update(scope_type="organization")
    control.objects.filter(suspended=True).update(activated_at=models.F("updated_at"))


def validate_safe_reverse(apps, schema_editor):
    control = apps.get_model("agents", "AgentRuntimeControl")
    if control.objects.filter(scope_type__in=("project", "scenario")).exists():
        raise RuntimeError(
            "Cannot safely reverse unified runtime controls while project/scenario rows exist"
        )


def drop_legacy_global_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP INDEX IF EXISTS uniq_agent_runtime_control_global")


def restore_legacy_global_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uniq_agent_runtime_control_global "
            "ON agents_agentruntimecontrol ((1)) WHERE organization_id IS NULL"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0005_remove_agentrunevent_run_and_more"),
        ("catalog", "0007_remove_scenario_type"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="agentruntimecontrol",
            name="uniq_agent_runtime_control_org",
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="scope_type",
            field=models.CharField(
                choices=[
                    ("platform", "Platform"),
                    ("organization", "Organization"),
                    ("project", "Project"),
                    ("scenario", "Scenario"),
                ],
                default="organization",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="runtime_controls",
                to="catalog.aiproject",
            ),
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="scenario",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="runtime_controls",
                to="catalog.scenario",
            ),
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="reason_code",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="source",
            field=models.CharField(
                choices=[
                    ("human", "Human"),
                    ("automatic", "Automatic"),
                    ("policy", "Policy"),
                ],
                default="human",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="requires_privileged_resume",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agentruntimecontrol",
            name="activated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(migrate_existing_controls, validate_safe_reverse),
        migrations.RunPython(drop_legacy_global_index, restore_legacy_global_index),
        migrations.AddConstraint(
            model_name="agentruntimecontrol",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        scope_type="platform",
                        organization__isnull=True,
                        project__isnull=True,
                        scenario__isnull=True,
                    )
                    | models.Q(
                        scope_type="organization",
                        organization__isnull=False,
                        project__isnull=True,
                        scenario__isnull=True,
                    )
                    | models.Q(
                        scope_type="project",
                        organization__isnull=False,
                        project__isnull=False,
                        scenario__isnull=True,
                    )
                    | models.Q(
                        scope_type="scenario",
                        organization__isnull=False,
                        project__isnull=True,
                        scenario__isnull=False,
                    )
                ),
                name="runtime_control_exact_scope",
            ),
        ),
        migrations.AddConstraint(
            model_name="agentruntimecontrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="platform"),
                fields=("scope_type",),
                name="uniq_runtime_control_platform",
            ),
        ),
        migrations.AddConstraint(
            model_name="agentruntimecontrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="organization"),
                fields=("organization",),
                name="uniq_runtime_control_org",
            ),
        ),
        migrations.AddConstraint(
            model_name="agentruntimecontrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="project"),
                fields=("project",),
                name="uniq_runtime_control_project",
            ),
        ),
        migrations.AddConstraint(
            model_name="agentruntimecontrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(scope_type="scenario"),
                fields=("scenario",),
                name="uniq_runtime_control_scenario",
            ),
        ),
    ]
