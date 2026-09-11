import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial"), ("tenancy", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scenarios",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            sql="""
                UPDATE catalog_scenario
                SET organization_id = (
                    SELECT catalog_aiproject.organization_id
                    FROM catalog_aiproject
                    WHERE catalog_aiproject.id = catalog_scenario.project_id
                )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="scenario",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scenarios",
                to="tenancy.organization",
            ),
        ),
    ]
