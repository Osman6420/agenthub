"""Cancel a pending or approved tool invocation without any external call."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.identity.authorization import Capability, authorize
from apps.tools.approvals import ToolApprovalError, cancel_invocation
from apps.tools.authz import resolve_actor
from apps.tools.models import ToolInvocation


class Command(BaseCommand):
    help = "Cancel a pending or approved tool invocation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--invocation", required=True, type=int)
        parser.add_argument("--actor", required=True, help="Django username of the operator.")

    def handle(self, *args: Any, **options: Any) -> None:
        invocation = ToolInvocation.objects.filter(pk=options["invocation"]).first()
        if invocation is None:
            raise CommandError(f"invocation not found: {options['invocation']}")
        actor = resolve_actor(username=options["actor"])
        if (
            actor is None
            or not authorize(
                user=actor,
                capability=Capability.RUNTIME_CANCEL,
                organization=invocation.organization,
                project=invocation.scenario.project,
                scenario=invocation.scenario,
            ).allowed
        ):
            raise CommandError("not authorized: UNKNOWN_ACTOR")
        try:
            cancelled = cancel_invocation(
                invocation_id=invocation.pk,
                organization_id=invocation.organization_id,
                actor=actor,
            )
        except ToolApprovalError as exc:
            raise CommandError(f"cancel denied: {exc.code}") from exc
        self.stdout.write(
            self.style.SUCCESS(f"invocation id={cancelled.pk} status={cancelled.status}")
        )
