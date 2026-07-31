"""Run a candidate release's pinned eval suite and print the redacted result."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.evaluations.services import EvalError, run_eval
from apps.releases.authz import ReleaseAuthorizationError, resolve_release_manager
from apps.releases.models import ScenarioRelease


class Command(BaseCommand):
    help = "Evaluate a candidate release against its manifest-pinned eval suite."

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
            resolve_release_manager(
                username=options["actor"],
                organization_id=organization_id,
                scenario=release.scenario,
            )
        except ReleaseAuthorizationError as exc:
            raise CommandError(f"not authorized: {exc.code}") from exc
        try:
            run = run_eval(release=release, created_by=options["actor"])
        except EvalError as exc:
            raise CommandError(f"eval could not start: {exc.code}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"eval run id={run.pk} status={run.status} "
                f"passed={run.passed_cases}/{run.total_cases}"
            )
        )
