from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0003_direct_tenant_lineage")]
    operations = [
        migrations.AddField(
            model_name="consumer", name="public_id",
            field=models.UUIDField(null=True, editable=False),
        ),
    ]
