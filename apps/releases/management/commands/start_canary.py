"""Route one consumer to an evaluated candidate release for a bounded window."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.identity.models import Consumer
from apps.releases.authz import ReleaseAuthorizationError, resolve_release_manager
from apps.releases.lifecycle import LifecycleError, start_canary
from apps.releases.models import ScenarioRelease


class Command(BaseCommand):
    help = "Assign a consumer to a candidate release as a time-bounded canary."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--release", required=True, type=int)
        parser.add_argument(
            "--consumer", required=True, help="Consumer subject in the release org."
        )
        parser.add_argument("--ttl", required=True, type=int, help="Canary lifetime in seconds.")
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
        consumer = Consumer.objects.filter(
            organization_id=organization_id, subject=options["consumer"]
        ).first()
        if consumer is None:
            raise CommandError(f"consumer not found in release org: {options['consumer']}")
        try:
            canary = start_canary(
                release=release,
                consumer=consumer,
                ttl_seconds=options["ttl"],
                actor=options["actor"],
            )
        except LifecycleError as exc:
            raise CommandError(f"canary denied: {exc.code}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"canary id={canary.pk} consumer={consumer.subject} "
                f"release={release.pk} expires_at={canary.expires_at.isoformat()}"
            )
        )
