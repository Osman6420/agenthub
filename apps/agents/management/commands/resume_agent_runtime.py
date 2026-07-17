"""Resume (clear) the agent runtime kill switch (platform-admin, audited) — P2.6.6.

Clears the fail-closed durable kill switch and re-dispatches claimable runs so runs that
were held during suspension proceed with their exact durable state. Scope is global by
default, or a single organization with ``--organization``. Restricted to a Django superuser
(``platform_admin``).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.agents.models import AgentRun, AgentRunStatus
from apps.agents.services import set_runtime_suspension
from apps.agents.tasks import execute_agent_run
from apps.tenancy.models import Organization
from apps.tenancy.services import is_platform_admin

_CLAIMABLE = (AgentRunStatus.QUEUED, AgentRunStatus.REQUESTED, AgentRunStatus.WAITING_APPROVAL)


class Command(BaseCommand):
    help = "Clear the global or per-organization agent runtime kill switch and re-dispatch runs."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True, help="Django username of the platform admin.")
        parser.add_argument(
            "--organization", help="Organization slug for a per-tenant switch (omit for global)."
        )
        parser.add_argument("--reason", default="", help="Safe reason recorded in the audit trail.")

    def handle(self, *args: Any, **options: Any) -> None:
        actor = str(options["actor"])
        user = get_user_model().objects.filter(username=actor).first()
        if user is None or not is_platform_admin(user):
            raise CommandError("resume denied: actor is not a platform admin")
        organization_id: int | None = None
        if options.get("organization"):
            org = Organization.objects.filter(slug=options["organization"]).first()
            if org is None:
                raise CommandError(f"organization not found: {options['organization']}")
            organization_id = org.id
        set_runtime_suspension(
            organization_id=organization_id,
            suspended=False,
            actor=actor,
            reason=str(options.get("reason", "")),
        )
        # Re-dispatch runs held during suspension. Dispatch is idempotent: the task claims
        # under select_for_update and a still-suspended peer scope simply no-ops again.
        runs = AgentRun.objects.filter(status__in=_CLAIMABLE)
        if organization_id is not None:
            runs = runs.filter(organization_id=organization_id)
        dispatched = 0
        for run_id, org_id in runs.values_list("id", "organization_id"):
            execute_agent_run.delay(run_id, org_id)
            dispatched += 1
        scope = "global" if organization_id is None else options["organization"]
        self.stdout.write(
            self.style.SUCCESS(f"agent runtime resumed scope={scope} redispatched={dispatched}")
        )
