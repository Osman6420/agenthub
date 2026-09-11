from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_scenario_organization")]
    operations = [
        migrations.AddField(
            model_name="aiproject",
            name="public_id",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name="scenario",
            name="public_id",
            field=models.UUIDField(null=True, editable=False),
        ),
    ]
