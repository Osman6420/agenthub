"""Drop the disposable pre-unification agent runtime tables."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0004_runtime_control_write_policy"),
        ("workflows", "0014_remove_workflowchildlink_child_agent_run_and_more"),
    ]

    operations = [
        migrations.DeleteModel(name="AgentRunEvent"),
        migrations.DeleteModel(name="AgentRun"),
        migrations.DeleteModel(name="AgentVersion"),
    ]
