from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0002_force_tenant_rls")]

    operations = [
        migrations.AlterField(
            model_name="organizationmembership",
            name="role",
            field=models.CharField(
                choices=[
                    ("platform_admin", "Platform admin"),
                    ("organization_admin", "Organization admin"),
                    ("document_manager", "Document manager"),
                    ("project_owner", "Project owner"),
                    ("scenario_editor", "Scenario editor"),
                    ("release_manager", "Release manager"),
                    ("approver", "Approver"),
                    ("auditor", "Auditor"),
                ],
                max_length=32,
            ),
        )
    ]
