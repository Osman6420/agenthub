"""Atomically roll back to a previously superseded release."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.releases.authz import ReleaseAuthorizationError, resolve_release_manager
from apps.releases.lifecycle import LifecycleError, rollback
from apps.releases.models import ScenarioRelease


class Command(BaseCommand):
    help = "Restore a superseded release as the active one for its scenario."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--target", required=True, type=int, help="Superseded release id.")
        parser.add_argument(
            "--actor", required=True, help="Django username of the acting operator."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        target = (
            ScenarioRelease.objects.select_related("scenario__project__organization")
            .filter(pk=options["target"])
            .first()
        )
        if target is None:
            raise CommandError(f"release not found: {options['target']}")
        organization_id = target.scenario.project.organization_id
        try:
            resolve_release_manager(username=options["actor"], organization_id=organization_id)
        except ReleaseAuthorizationError as exc:
            raise CommandError(f"not authorized: {exc.code}") from exc
        try:
            rollback(scenario=target.scenario, target=target, actor=options["actor"])
        except LifecycleError as exc:
            raise CommandError(f"rollback denied: {exc.code}") from exc
        self.stdout.write(self.style.SUCCESS(f"rolled back to release id={target.pk}"))
