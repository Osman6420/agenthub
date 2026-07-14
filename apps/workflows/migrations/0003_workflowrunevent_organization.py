import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0001_initial"),
        ("workflows", "0002_workflowrun_awaiting_node_alter_workflowrun_status"),
    ]
    operations = [
        migrations.AddField(
            model_name="workflowrunevent",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workflow_run_events",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            """UPDATE workflows_workflowrunevent SET organization_id =
            (SELECT workflows_workflowrun.organization_id FROM workflows_workflowrun
             WHERE workflows_workflowrun.id = workflows_workflowrunevent.run_id)""",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="workflowrunevent",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workflow_run_events",
                to="tenancy.organization",
            ),
        ),
    ]
