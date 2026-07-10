"""Import artifact definitions from a directory of GitOps YAML files.

Validates each document (schema + inline-secret rejection) before persisting. Use
``--dry-run`` to validate without writing. Every created artifact is audited.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.artifacts.gitops import GitOpsError, import_document
from apps.audit.services import record_event
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Import artifact GitOps YAML files into the artifact registry."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--path", required=True, help="Directory of YAML files.")
        parser.add_argument(
            "--organization",
            default=None,
            help="Default organization slug when a document omits metadata.organization.",
        )
        parser.add_argument("--actor", default="cli", help="Actor id for audit.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        root = Path(options["path"])
        if not root.is_dir():
            raise CommandError(f"not a directory: {root}")

        default_org = None
        if options["organization"]:
            default_org = Organization.objects.filter(slug=options["organization"]).first()
            if default_org is None:
                raise CommandError(f"unknown organization: {options['organization']}")

        files = sorted(p for p in root.rglob("*") if p.suffix in {".yaml", ".yml"})
        created = 0
        try:
            with transaction.atomic():
                for path in files:
                    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                        if doc is None:
                            continue
                        try:
                            artifact = import_document(
                                doc,
                                default_organization=default_org,
                                created_by=options["actor"],
                                source_git_revision="",
                            )
                        except (GitOpsError, ValueError) as exc:
                            raise CommandError(f"{path}: {exc}") from exc
                        created += 1
                        self.stdout.write(f"imported {artifact.type} {artifact.ref} [{path.name}]")
                        if not options["dry_run"]:
                            record_event(
                                actor_type="user",
                                actor_id=options["actor"],
                                action="artifact.import",
                                outcome="success",
                                organization_id=artifact.organization_id,
                                resource_type="artifact_version",
                                resource_id=artifact.ref,
                            )
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except CommandError:
            raise
        verb = "validated" if options["dry_run"] else "imported"
        self.stdout.write(self.style.SUCCESS(f"{verb} {created} artifact(s)"))
