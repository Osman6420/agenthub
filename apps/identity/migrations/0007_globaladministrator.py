import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("identity", "0006_consumer_public_id_constrain"),
    ]

    operations = [
        migrations.CreateModel(
            name="GlobalAdministrator",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "scope",
                    models.CharField(
                        default="global",
                        editable=False,
                        max_length=16,
                        unique=True,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="global_administrator",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "global administrator",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("scope", "global")),
                        name="global_administrator_single_scope",
                    )
                ],
            },
        ),
    ]
