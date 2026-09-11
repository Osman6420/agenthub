import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0005_consumer_public_id_backfill")]
    operations = [
        migrations.AlterField(
            model_name="consumer", name="public_id",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
