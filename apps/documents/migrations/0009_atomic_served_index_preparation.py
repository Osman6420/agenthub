from django.db import migrations

PUBLISHED_SET_STATUSES = ("promotable", "active", "superseded")


def reconcile_served_pairs(apps, schema_editor):
    DocumentSet = apps.get_model("documents", "DocumentSet")
    DocumentSetVersion = apps.get_model("documents", "DocumentSetVersion")
    IndexVersion = apps.get_model("ingestion", "IndexVersion")

    for document_set_id in DocumentSet.objects.order_by("pk").values_list("pk", flat=True):
        versions = DocumentSetVersion.objects.filter(document_set_id=document_set_id).order_by(
            "-version", "-pk"
        )
        version_ids = list(versions.values_list("pk", flat=True))
        candidate_index = (
            IndexVersion.objects.filter(
                document_set_version_id__in=version_ids,
                document_set_version__status__in=PUBLISHED_SET_STATUSES,
                status="active",
                store_ready=True,
            )
            .order_by("-updated_at", "-pk")
            .first()
        )
        if candidate_index is None:
            candidate_version = (
                versions.filter(
                    status="active",
                    built_index_version__store_ready=True,
                    built_index_version__status__in=("promotable", "active"),
                )
                .select_related("built_index_version")
                .first()
            )
            candidate_index = (
                candidate_version.built_index_version if candidate_version is not None else None
            )

        DocumentSetVersion.objects.filter(document_set_id=document_set_id, status="active").update(
            status="superseded"
        )
        IndexVersion.objects.filter(
            document_set_version_id__in=version_ids, status="active"
        ).update(status="superseded")
        if candidate_index is None:
            continue
        DocumentSetVersion.objects.filter(pk=candidate_index.document_set_version_id).update(
            status="active", built_index_version_id=candidate_index.pk
        )
        IndexVersion.objects.filter(pk=candidate_index.pk).update(status="active")


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0008_document_set_quarantine"),
        ("ingestion", "0012_document_profiles_index_automation"),
    ]

    operations = [
        migrations.RunPython(reconcile_served_pairs, migrations.RunPython.noop),
    ]
