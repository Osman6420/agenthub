import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_scenario_organization"),
        ("identity", "0002_consumertoken"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="consumerbinding",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consumer_bindings",
                to="tenancy.organization",
            ),
        ),
        migrations.AddField(
            model_name="consumertoken",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consumer_tokens",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            sql="""
                UPDATE identity_consumerbinding
                SET organization_id = (
                    SELECT identity_consumer.organization_id FROM identity_consumer
                    WHERE identity_consumer.id = identity_consumerbinding.consumer_id
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                UPDATE identity_consumertoken
                SET organization_id = (
                    SELECT identity_consumer.organization_id FROM identity_consumer
                    WHERE identity_consumer.id = identity_consumertoken.consumer_id
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="consumerbinding",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consumer_bindings",
                to="tenancy.organization",
            ),
        ),
        migrations.AlterField(
            model_name="consumertoken",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consumer_tokens",
                to="tenancy.organization",
            ),
        ),
    ]
