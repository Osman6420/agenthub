from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0007_document_version_summary")]

    operations = [
        migrations.AlterField(
            model_name="documentset",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("quarantined", "Quarantined"),
                    ("archived", "Archived"),
                ],
                default="active",
                max_length=16,
            ),
        )
    ]
