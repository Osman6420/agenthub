from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services import record_event
from apps.ingestion.models import IndexVersion
from apps.ingestion.staged_build import (
    StagedBuildError,
    promote_staged_index,
    rollback_staged_index,
)
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import can_manage_document_set_operations


class Command(BaseCommand):
    help = "Pointer-flip promote (or --rollback restore) a staged per-document-set index version."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--index-version", type=int, required=True)
        parser.add_argument(
            "--rollback",
            action="store_true",
            help="Restore a superseded index version instead of promoting a promotable one.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = options["actor"]
        actor = get_user_model().objects.filter(username=username, is_active=True).first()
        if actor is None:
            raise CommandError("active actor not found")
        denied = False
        lifecycle_error: StagedBuildError | None = None
        result: IndexVersion | None = None
        verb = ""
        with transaction.atomic():
            index = self._resolve_index(options["index_version"])
            if index is None or index.document_set_version is None:
                raise CommandError("index version not found")
            document_set = index.document_set_version.document_set
            if not can_manage_document_set_operations(actor, document_set):
                record_event(
                    actor_type="user",
                    actor_id=username,
                    action="ingestion.staged_index.rolled_back"
                    if options["rollback"]
                    else "ingestion.staged_index.promoted",
                    outcome="deny",
                    organization_id=index.organization_id,
                    resource_type="index_version",
                    resource_id=str(index.pk),
                    reason="DOCUMENT_SET_OPERATIONS_AUTHORITY_REQUIRED",
                )
                denied = True
            else:
                try:
                    if options["rollback"]:
                        result = rollback_staged_index(index, actor=username)
                        verb = "rolled back to"
                    else:
                        result = promote_staged_index(index, actor=username)
                        verb = "promoted to"
                except StagedBuildError as exc:
                    lifecycle_error = exc
        if denied:
            raise CommandError("not authorized for document-set operations")
        if lifecycle_error is not None:
            raise CommandError(str(lifecycle_error)) from lifecycle_error
        if result is None:  # pragma: no cover - defensive invariant
            raise CommandError("index lifecycle result missing")
        self.stdout.write(self.style.SUCCESS(f"IndexVersion {result.pk} {verb} {result.status}"))

    @staticmethod
    def _resolve_index(index_version_id: int) -> IndexVersion | None:
        """Resolve tenant data under FORCE RLS without requiring a privileged database role."""
        for organization_id in Organization.objects.order_by("pk").values_list("pk", flat=True):
            set_tenant_context(organization_id)
            index = (
                IndexVersion.objects.select_related("document_set_version__document_set")
                .filter(pk=index_version_id)
                .first()
            )
            if index is not None:
                return index
        return None
