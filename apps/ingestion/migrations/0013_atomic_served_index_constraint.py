from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0010_active_document_set_version_constraint"),
        ("ingestion", "0012_document_profiles_index_automation"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="indexversion",
            constraint=models.UniqueConstraint(
                fields=("document_set_version",),
                condition=models.Q(
                    document_set_version__isnull=False,
                    status="active",
                ),
                name="uniq_active_index_per_set_version",
            ),
        )
    ]
