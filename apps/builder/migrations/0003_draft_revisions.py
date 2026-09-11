import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("builder", "0002_artifactdraft"), ("catalog", "0002_scenario_organization")]

    operations = [
        migrations.AddField(
            model_name="workflowdraft",
            name="revision",
            field=models.PositiveBigIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="workflowdraft",
            name="scenario",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="workflow_drafts",
                to="catalog.scenario",
            ),
        ),
        migrations.AddField(
            model_name="artifactdraft",
            name="revision",
            field=models.PositiveBigIntegerField(default=1),
        ),
    ]
