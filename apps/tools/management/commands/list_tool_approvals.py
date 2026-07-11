"""List pending tool approval requests for an organization (operator visibility)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.tenancy.models import Organization
from apps.tools.models import ApprovalRequest, ApprovalStatus


class Command(BaseCommand):
    help = "List pending tool approval requests for an organization."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True, help="Organization slug.")

    def handle(self, *args: Any, **options: Any) -> None:
        org = Organization.objects.filter(slug=options["organization"]).first()
        if org is None:
            raise CommandError(f"organization not found: {options['organization']}")
        pending = ApprovalRequest.objects.filter(
            organization=org, status=ApprovalStatus.PENDING
        ).order_by("expires_at")
        if not pending:
            self.stdout.write("no pending approvals")
            return
        for approval in pending:
            self.stdout.write(
                f"approval id={approval.pk} invocation={approval.invocation_id} "
                f"expires_at={approval.expires_at.isoformat()} roles={approval.approver_roles}"
            )
