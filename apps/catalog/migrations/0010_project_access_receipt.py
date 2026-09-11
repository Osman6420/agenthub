from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0009_scenario_access_inheritance")]

    operations = [
        migrations.AddField(
            model_name="aiproject",
            name="access_revision",
            field=models.PositiveIntegerField(default=0, db_default=0),
        ),
        migrations.AddField(
            model_name="aiproject",
            name="access_change_id",
            field=models.CharField(max_length=64, blank=True, default="", db_default=""),
        ),
    ]
