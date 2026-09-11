import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agents", "0001_initial"), ("tenancy", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="agentrunevent",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="agent_run_events",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            """UPDATE agents_agentrunevent SET organization_id =
            (SELECT agents_agentrun.organization_id FROM agents_agentrun
             WHERE agents_agentrun.id = agents_agentrunevent.run_id)""",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="agentrunevent",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="agent_run_events",
                to="tenancy.organization",
            ),
        ),
    ]
