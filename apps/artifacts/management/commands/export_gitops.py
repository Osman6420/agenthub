"""Export an organization's artifact versions to GitOps YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.core.management.base import BaseCommand, CommandError

from apps.artifacts.gitops import artifact_to_document
from apps.artifacts.models import ArtifactVersion
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Export artifact versions for an organization as GitOps YAML."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True)
        parser.add_argument("--path", default=None, help="Output directory (default: stdout).")

    def handle(self, *args: Any, **options: Any) -> None:
        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError(f"unknown organization: {options['organization']}")

        out_dir = Path(options["path"]) if options["path"] else None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for artifact in ArtifactVersion.objects.filter(organization=organization):
            document = artifact_to_document(artifact)
            text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
            if out_dir is None:
                self.stdout.write("---")
                self.stdout.write(text)
            else:
                filename = f"{artifact.type}__{artifact.logical_id}.v{artifact.version}.yaml"
                (out_dir / filename).write_text(text, encoding="utf-8")
            count += 1

        self.stdout.write(self.style.SUCCESS(f"exported {count} artifact(s)"))
