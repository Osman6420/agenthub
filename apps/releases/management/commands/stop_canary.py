"""Stop an active canary assignment."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.releases.authz import ReleaseAuthorizationError, resolve_release_manager
from apps.releases.lifecycle import LifecycleError, stop_canary
from apps.releases.models import ReleaseCanary


class Command(BaseCommand):
    help = "Stop an active canary assignment by id."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--canary", required=True, type=int)
        parser.add_argument(
            "--actor", required=True, help="Django username of the acting operator."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        canary = (
            ReleaseCanary.objects.select_related("scenario__project__organization")
            .filter(pk=options["canary"])
            .first()
        )
        if canary is None:
            raise CommandError(f"canary not found: {options['canary']}")
        organization_id = canary.scenario.project.organization_id
        try:
            resolve_release_manager(
                username=options["actor"],
                organization_id=organization_id,
                scenario=canary.scenario,
            )
        except ReleaseAuthorizationError as exc:
            raise CommandError(f"not authorized: {exc.code}") from exc
        try:
            stop_canary(canary=canary, actor=options["actor"])
        except LifecycleError as exc:
            raise CommandError(f"stop denied: {exc.code}") from exc
        self.stdout.write(self.style.SUCCESS(f"stopped canary id={canary.pk}"))
