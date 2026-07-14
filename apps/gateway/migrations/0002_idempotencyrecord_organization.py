import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gateway", "0001_initial"),
        ("identity", "0003_direct_tenant_lineage"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="idempotencyrecord",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="idempotency_records",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            sql="""
                UPDATE gateway_idempotencyrecord
                SET organization_id = (
                    SELECT identity_consumer.organization_id FROM identity_consumer
                    WHERE identity_consumer.id = gateway_idempotencyrecord.consumer_id
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="idempotencyrecord",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="idempotency_records",
                to="tenancy.organization",
            ),
        ),
    ]
