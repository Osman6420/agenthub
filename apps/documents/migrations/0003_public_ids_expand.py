from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_documentsetgrant_scenariodocumentsetbinding")]
    operations = [
        migrations.AddField(
            model_name="document", name="public_id",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name="documentset", name="public_id",
            field=models.UUIDField(null=True, editable=False),
        ),
    ]
