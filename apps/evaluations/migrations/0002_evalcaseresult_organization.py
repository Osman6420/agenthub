import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("evaluations", "0001_initial"), ("tenancy", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="evalcaseresult",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="eval_case_results",
                to="tenancy.organization",
            ),
        ),
        migrations.RunSQL(
            """UPDATE evaluations_evalcaseresult SET organization_id =
            (SELECT evaluations_evalrun.organization_id FROM evaluations_evalrun
             WHERE evaluations_evalrun.id = evaluations_evalcaseresult.run_id)""",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="evalcaseresult",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="eval_case_results",
                to="tenancy.organization",
            ),
        ),
    ]
