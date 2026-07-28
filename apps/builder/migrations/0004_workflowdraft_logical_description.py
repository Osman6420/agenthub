from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("builder", "0003_draft_revisions"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowdraft",
            name="logical_description",
            field=models.TextField(
                blank=True,
                help_text="Stable purpose of the logical artifact across published versions.",
                max_length=1000,
            ),
        ),
    ]
