from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0009_atomic_served_index_preparation")]

    operations = [
        migrations.AddConstraint(
            model_name="documentsetversion",
            constraint=models.UniqueConstraint(
                fields=("document_set",),
                condition=models.Q(status="active"),
                name="uniq_active_document_set_version",
            ),
        ),
    ]
