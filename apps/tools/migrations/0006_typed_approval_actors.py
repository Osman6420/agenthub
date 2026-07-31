from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tools", "0005_remove_approvalrequest_approver_roles"),
    ]

    operations = [
        migrations.RenameField(
            model_name="approvalrequest",
            old_name="requested_by_user",
            new_name="initiated_by_user",
        ),
        migrations.RemoveField(
            model_name="approvalrequest",
            name="requested_by",
        ),
        migrations.RemoveField(
            model_name="approvalrequest",
            name="decided_by",
        ),
    ]
