"""Fail-closed promotion of a candidate/canary release to active."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.releases.authz import ReleaseAuthorizationError, resolve_release_manager
from apps.releases.lifecycle import LifecycleError, promote
from apps.releases.models import ScenarioRelease


class Command(BaseCommand):
    help = "Promote a release to active (requires a passing eval and ready pinned indexes)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--release", required=True, type=int)
        parser.add_argument(
            "--actor", required=True, help="Django username of the acting operator."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        release = (
            ScenarioRelease.objects.select_related("scenario__project__organization")
            .filter(pk=options["release"])
            .first()
        )
        if release is None:
            raise CommandError(f"release not found: {options['release']}")
        organization_id = release.scenario.project.organization_id
        try:
            resolve_release_manager(username=options["actor"], organization_id=organization_id)
        except ReleaseAuthorizationError as exc:
            raise CommandError(f"not authorized: {exc.code}") from exc
        try:
            promote(release=release, actor=options["actor"])
        except LifecycleError as exc:
            raise CommandError(f"promotion denied: {exc.code}") from exc
        self.stdout.write(self.style.SUCCESS(f"promoted release id={release.pk} to active"))
