"""Cancel an in-flight agent run as an operator (tenant-scoped, audited).

Cancellation is idempotent and never resurrects a terminal run. The runtime observes
the cancelled status at its next guard check and stops without any external call.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.agents.models import AgentRun
from apps.agents.services import AgentRequestError, operator_cancel_agent_run
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Cancel an agent run by its public id."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True, help="Organization slug.")
        parser.add_argument("--run", required=True, help="Agent run public id (UUID).")
        parser.add_argument("--actor", required=True, help="Django username of the operator.")

    def handle(self, *args: Any, **options: Any) -> None:
        org = Organization.objects.filter(slug=options["organization"]).first()
        if org is None:
            raise CommandError(f"organization not found: {options['organization']}")
        try:
            public_id = uuid.UUID(str(options["run"]))
        except ValueError as exc:
            raise CommandError(f"invalid run id: {options['run']}") from exc
        run = AgentRun.objects.filter(public_id=public_id, organization=org).first()
        if run is None:
            raise CommandError(f"agent run not found: {options['run']}")
        try:
            cancelled = operator_cancel_agent_run(
                run=run, organization_id=org.id, actor=options["actor"]
            )
        except AgentRequestError as exc:
            raise CommandError(f"cancel denied: {exc.code}") from exc
        self.stdout.write(
            self.style.SUCCESS(f"run={cancelled.public_id} status={cancelled.status}")
        )
