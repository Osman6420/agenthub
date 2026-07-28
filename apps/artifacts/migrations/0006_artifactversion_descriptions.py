from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("artifacts", "0005_alter_artifactversion_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifactversion",
            name="logical_description",
            field=models.TextField(
                blank=True,
                help_text="Human explanation of the stable logical artifact across versions.",
                max_length=1000,
            ),
        ),
        migrations.AddField(
            model_name="artifactversion",
            name="version_description",
            field=models.TextField(
                blank=True,
                help_text="Human explanation of what this exact immutable version contains or changes.",
                max_length=1000,
            ),
        ),
    ]
