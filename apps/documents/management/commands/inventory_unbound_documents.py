import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef

from apps.documents.models import Document, DocumentSetMembership
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Dry-run inventory of documents with no document-set membership; never deletes data."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="Exact organization slug")
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if not 1 <= limit <= 10_000:
            raise CommandError("limit must be between 1 and 10000")
        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError("organization not found")
        with transaction.atomic():
            set_tenant_context(organization.pk)
            membership = DocumentSetMembership.objects.filter(
                document_version__document_id=OuterRef("pk")
            )
            queryset = (
                Document.objects.filter(organization=organization)
                .annotate(has_membership=Exists(membership))
                .filter(has_membership=False)
            )
            total = queryset.count()
            rows = list(
                queryset.order_by("pk")
                .prefetch_related("versions")
                .select_related("source")[:limit]
            )
        payload = {
            "schema": 1,
            "dry_run": True,
            "organization": {
                "id": organization.pk,
                "slug": organization.slug,
            },
            "total": total,
            "truncated": total > len(rows),
            "cleanup_authorized": False,
            "protection_checks": {
                "published_pin": "clear",
                "retention_or_legal_hold": "model_unavailable_refuse_apply",
                "backup": "not_verified",
                "object_store": "not_verified",
            },
            "documents": [
                {
                    "id": document.pk,
                    "public_id": str(document.public_id),
                    "logical_id": document.logical_id,
                    "source_id": document.source_id,
                    "lifecycle_state": document.lifecycle_state,
                    "current_version": document.current_version,
                    "versions": [
                        {
                            "id": version.pk,
                            "version": version.version,
                            "checksum": version.checksum,
                            "byte_size": version.byte_size,
                        }
                        for version in document.versions.all()
                    ],
                }
                for document in rows
            ],
        }
        self.stdout.write(json.dumps(payload, sort_keys=True))
