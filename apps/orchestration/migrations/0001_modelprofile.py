import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="ModelProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("logical_id", models.CharField(max_length=128)),
                ("revision", models.PositiveIntegerField()),
                ("provider", models.CharField(default="openai_compatible", max_length=64)),
                ("scheme", models.CharField(default="https", max_length=8)),
                ("host", models.CharField(max_length=253)),
                ("port", models.PositiveIntegerField(default=443)),
                ("path", models.CharField(default="/v1/chat/completions", max_length=512)),
                ("model", models.CharField(max_length=200)),
                ("secret_ref", models.CharField(max_length=160)),
                ("timeout_seconds", models.PositiveIntegerField(default=30)),
                ("max_response_bytes", models.PositiveIntegerField(default=1000000)),
                ("max_output_tokens", models.PositiveIntegerField(default=2048)),
                ("status", models.CharField(choices=[("active", "Active"), ("disabled", "Disabled")], default="active", max_length=16)),
                ("created_by", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("logical_id", "revision"), name="uniq_model_profile_logical_revision")],
            },
        )
    ]
