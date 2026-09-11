from __future__ import annotations

import uuid

from django.db import migrations, models
import django.db.models.deletion


def enable_wait_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quoted = schema_editor.quote_name("workflows_workflowwait")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"""CREATE POLICY tenant_isolation ON {quoted}
            USING (agenthub_tenant_scope_contains(organization_id))
            WITH CHECK (agenthub_tenant_scope_contains(organization_id))"""
        )


def disable_wait_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    quoted = schema_editor.quote_name("workflows_workflowwait")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {quoted}")
        cursor.execute(f"ALTER TABLE {quoted} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {quoted} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0002_force_tenant_rls"),
        ("workflows", "0004_workflowbranch_workflowjoin"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("requested", "Requested"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("waiting_approval", "Waiting approval"),
                    ("waiting_event", "Waiting event"),
                    ("waiting_human", "Waiting human"),
                    ("waiting_timer", "Waiting timer"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                    ("timed_out", "Timed out"),
                    ("cancelled", "Cancelled"),
                ],
                default="requested",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="WorkflowWait",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("kind", models.CharField(choices=[("event", "Event"), ("timer", "Timer"), ("human", "Human")], max_length=16)),
                ("node_id", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("resumed", "Resumed"), ("expired", "Expired"), ("cancelled", "Cancelled")], default="pending", max_length=16)),
                ("correlation_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("pending_checksum", models.CharField(max_length=64)),
                ("workflow_checksum", models.CharField(max_length=64)),
                ("release_id_snapshot", models.PositiveBigIntegerField()),
                ("compiler_version", models.CharField(max_length=32)),
                ("payload_schema", models.JSONField(blank=True, default=dict)),
                ("output_mapping", models.JSONField(blank=True, default=list)),
                ("requester_subject", models.CharField(blank=True, max_length=255)),
                ("allowed_roles", models.JSONField(blank=True, default=list)),
                ("deny_self_decision", models.BooleanField(default=True)),
                ("escalation_role", models.CharField(blank=True, max_length=64)),
                ("escalation_timeout_seconds", models.PositiveIntegerField(default=0)),
                ("deadline_at", models.DateTimeField()),
                ("escalated_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_by", models.CharField(blank=True, max_length=255)),
                ("redacted_payload", models.JSONField(blank=True, default=dict)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workflow_waits", to="tenancy.organization")),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="waits", to="workflows.workflowrun")),
            ],
        ),
        migrations.AddConstraint(
            model_name="workflowwait",
            constraint=models.UniqueConstraint(fields=("run", "node_id"), name="uniq_workflow_wait_run_node"),
        ),
        migrations.AddIndex(
            model_name="workflowwait",
            index=models.Index(fields=["organization", "status", "deadline_at"], name="workflows_w_organiz_578972_idx"),
        ),
        migrations.RunPython(enable_wait_rls, disable_wait_rls),
    ]
