import uuid

from django.db import migrations


def backfill(apps, schema_editor):
    database = schema_editor.connection.alias
    for model_name in ("Document", "DocumentSet"):
        model = apps.get_model("documents", model_name)
        rows = model.objects.using(database).filter(public_id__isnull=True)
        for pk in rows.values_list("pk", flat=True).iterator(chunk_size=500):
            for _attempt in range(8):
                candidate = uuid.uuid4()
                if not model.objects.using(database).filter(public_id=candidate).exists():
                    model.objects.using(database).filter(
                        pk=pk, public_id__isnull=True
                    ).update(public_id=candidate)
                    break
            else:
                raise RuntimeError("PUBLIC_ID_BACKFILL_EXHAUSTED")


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_public_ids_expand")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
