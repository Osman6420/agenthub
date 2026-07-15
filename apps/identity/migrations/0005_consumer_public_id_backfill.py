import uuid

from django.db import migrations


def backfill(apps, schema_editor):
    database = schema_editor.connection.alias
    model = apps.get_model("identity", "Consumer")
    rows = model.objects.using(database).filter(public_id__isnull=True)
    for pk in rows.values_list("pk", flat=True).iterator(chunk_size=500):
        for _attempt in range(8):
            candidate = uuid.uuid4()
            if not model.objects.using(database).filter(public_id=candidate).exists():
                model.objects.using(database).filter(pk=pk, public_id__isnull=True).update(
                    public_id=candidate
                )
                break
        else:
            raise RuntimeError("PUBLIC_ID_BACKFILL_EXHAUSTED")


class Migration(migrations.Migration):
    dependencies = [("identity", "0004_consumer_public_id_expand")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
