from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0010_run_transition_idempotency"),
    ]

    operations = [
        migrations.AddField(
            model_name="run",
            name="background_claim_checkpoint_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="background_claim_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="background_claim_token",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ("background_claim_checkpoint_version__isnull", True),
                        ("background_claim_expires_at__isnull", True),
                        ("background_claim_token__isnull", True),
                    )
                    | models.Q(
                        ("background_claim_checkpoint_version__isnull", False),
                        ("background_claim_expires_at__isnull", False),
                        ("background_claim_token__isnull", False),
                        ("execution_mode", "background"),
                    )
                ),
                name="run_background_claim_complete",
            ),
        ),
    ]
