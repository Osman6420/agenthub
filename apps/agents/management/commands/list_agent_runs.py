"""List agent runs for an organization (operator visibility).

Output is redacted by construction: only bounded, non-sensitive fields (public id,
status, counters, error code) are printed — never the checkpoint, objective, or any
tool payload.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.agents.models import AgentRun, AgentRunStatus
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "List agent runs for an organization (redacted operator view)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True, help="Organization slug.")
        parser.add_argument(
            "--status",
            choices=[value for value, _ in AgentRunStatus.choices],
            help="Optional status filter.",
        )
        parser.add_argument("--limit", type=int, default=50, help="Maximum rows (1..500).")

    def handle(self, *args: Any, **options: Any) -> None:
        org = Organization.objects.filter(slug=options["organization"]).first()
        if org is None:
            raise CommandError(f"organization not found: {options['organization']}")
        limit = max(1, min(int(options["limit"]), 500))
        runs = AgentRun.objects.filter(organization=org)
        if options.get("status"):
            runs = runs.filter(status=options["status"])
        runs = runs.order_by("-created_at")[:limit]
        if not runs:
            self.stdout.write("no agent runs")
            return
        for run in runs:
            self.stdout.write(
                f"run={run.public_id} status={run.status} steps={run.step_count} "
                f"tool_calls={run.tool_call_count} error={run.error_code or '-'} "
                f"created_at={run.created_at.isoformat()}"
            )
