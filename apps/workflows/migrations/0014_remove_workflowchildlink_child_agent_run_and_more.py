"""Drop the disposable pre-unification workflow runtime tables."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0013_run_parallel_region"),
    ]

    operations = [
        migrations.DeleteModel(name="WorkflowChildLink"),
        migrations.DeleteModel(name="WorkflowRecoveryApproval"),
        migrations.DeleteModel(name="WorkflowRunEvent"),
        migrations.DeleteModel(name="WorkflowWait"),
        migrations.DeleteModel(name="WorkflowBranch"),
        migrations.DeleteModel(name="WorkflowCompensationEntry"),
        migrations.DeleteModel(name="WorkflowJoin"),
        migrations.DeleteModel(name="WorkflowNodeAttempt"),
        migrations.DeleteModel(name="WorkflowRecoveryCase"),
        migrations.DeleteModel(name="WorkflowRun"),
    ]
