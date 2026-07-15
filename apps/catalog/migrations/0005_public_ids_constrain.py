import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0004_public_ids_backfill")]
    operations = [
        migrations.AlterField(
            model_name="aiproject", name="public_id",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="scenario", name="public_id",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
