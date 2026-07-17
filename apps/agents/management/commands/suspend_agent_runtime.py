"""Suspend the agent runtime kill switch (platform-admin, audited) — P2.6.6.

Sets the fail-closed durable kill switch so the Celery task refuses to claim or resume
agent runs. Scope is global by default, or a single organization with ``--organization``.
Durable run state is preserved; ``resume_agent_runtime`` clears the switch and re-dispatches
claimable runs. Flipping the switch is restricted to a Django superuser (``platform_admin``).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.agents.services import set_runtime_suspension
from apps.tenancy.models import Organization
from apps.tenancy.services import is_platform_admin


class Command(BaseCommand):
    help = "Suspend the global or per-organization agent runtime kill switch."

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
            raise CommandError("suspend denied: actor is not a platform admin")
        organization_id: int | None = None
        if options.get("organization"):
            org = Organization.objects.filter(slug=options["organization"]).first()
            if org is None:
                raise CommandError(f"organization not found: {options['organization']}")
            organization_id = org.id
        control = set_runtime_suspension(
            organization_id=organization_id,
            suspended=True,
            actor=actor,
            reason=str(options.get("reason", "")),
        )
        scope = "global" if organization_id is None else options["organization"]
        self.stdout.write(
            self.style.SUCCESS(f"agent runtime suspended scope={scope} id={control.pk}")
        )
