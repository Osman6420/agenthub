"""Approve or reject a pending tool approval request (operator action)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.tools.approvals import ToolApprovalError, decide_approval
from apps.tools.authz import resolve_actor_roles
from apps.tools.models import ApprovalRequest


class Command(BaseCommand):
    help = "Approve or reject a pending tool approval request."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--approval", required=True, type=int)
        parser.add_argument("--actor", required=True, help="Django username of the operator.")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--approve", action="store_true")
        group.add_argument("--reject", action="store_true")
        parser.add_argument("--reason", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        approval = ApprovalRequest.objects.filter(pk=options["approval"]).first()
        if approval is None:
            raise CommandError(f"approval not found: {options['approval']}")
        roles = resolve_actor_roles(
            username=options["actor"], organization_id=approval.organization_id
        )
        if roles is None:
            raise CommandError("not authorized: UNKNOWN_ACTOR")
        try:
            decided = decide_approval(
                approval_id=approval.pk,
                organization_id=approval.organization_id,
                actor=options["actor"],
                actor_roles=roles,
                approve=bool(options["approve"]),
                reason=options["reason"],
            )
        except ToolApprovalError as exc:
            raise CommandError(f"decision denied: {exc.code}") from exc
        self.stdout.write(self.style.SUCCESS(f"approval id={decided.pk} status={decided.status}"))
