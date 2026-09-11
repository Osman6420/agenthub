"""Import create-only control-plane records from reviewed GitOps YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services import record_event
from apps.catalog.control_plane_gitops import (
    ControlPlaneGitOpsError,
    import_control_plane_document,
)


class Command(BaseCommand):
    help = "Import organizations, projects, scenarios, consumers, and bindings from YAML."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--path", required=True, help="YAML file or directory.")
        parser.add_argument("--actor", default="cli", help="Actor id for audit.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        root = Path(options["path"])
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(path for path in root.rglob("*") if path.suffix in {".yaml", ".yml"})
        else:
            raise CommandError(f"path does not exist: {root}")

        created = 0
        unchanged = 0
        try:
            with transaction.atomic():
                for path in files:
                    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                        if doc is None:
                            continue
                        try:
                            instance, was_created, organization_id = import_control_plane_document(
                                doc
                            )
                        except ControlPlaneGitOpsError as exc:
                            raise CommandError(f"{path}: {exc}") from exc
                        if was_created:
                            created += 1
                            record_event(
                                actor_type="user",
                                actor_id=options["actor"],
                                action="control_plane.import",
                                outcome="success",
                                organization_id=organization_id,
                                resource_type=instance._meta.model_name or "unknown",
                                resource_id=str(instance.pk),
                            )
                        else:
                            unchanged += 1
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except (OSError, yaml.YAMLError) as exc:
            raise CommandError(str(exc)) from exc

        verb = "validated" if options["dry_run"] else "imported"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {created} new, {unchanged} unchanged record(s)")
        )
