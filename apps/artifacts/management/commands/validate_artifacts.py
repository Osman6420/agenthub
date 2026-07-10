"""Re-validate stored artifacts: type validation, secret-safety, and checksum."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.validation import compute_checksum, validate_body
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Validate artifact bodies and checksums for an organization."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError(f"unknown organization: {options['organization']}")

        failures = 0
        checked = 0
        for artifact in ArtifactVersion.objects.filter(organization=organization):
            checked += 1
            try:
                validate_body(artifact.type, artifact.body)
            except ValueError as exc:
                failures += 1
                self.stderr.write(f"INVALID {artifact.ref}: {exc}")
                continue
            if compute_checksum(artifact.body) != artifact.checksum:
                failures += 1
                self.stderr.write(f"CHECKSUM DRIFT {artifact.ref}")

        self.stdout.write(f"checked {checked} artifact(s), {failures} failure(s)")
        if failures:
            raise CommandError(f"{failures} artifact(s) failed validation")
