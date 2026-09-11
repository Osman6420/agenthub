import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_scenario_organization"),
        ("releases", "0002_releasecanary"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenariorelease",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scenario_releases",
                to="tenancy.organization",
            ),
        ),
        migrations.AddField(
            model_name="releasecanary",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="release_canaries",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            """UPDATE releases_scenariorelease SET organization_id =
            (SELECT catalog_scenario.organization_id FROM catalog_scenario
             WHERE catalog_scenario.id = releases_scenariorelease.scenario_id)""",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            """UPDATE releases_releasecanary SET organization_id =
            (SELECT catalog_scenario.organization_id FROM catalog_scenario
             WHERE catalog_scenario.id = releases_releasecanary.scenario_id)""",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="scenariorelease",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scenario_releases",
                to="tenancy.organization",
            ),
        ),
        migrations.AlterField(
            model_name="releasecanary",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="release_canaries",
                to="tenancy.organization",
            ),
        ),
    ]
