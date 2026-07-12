from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import IndexVersion
from apps.ingestion.staged_build import (
    StagedBuildError,
    promote_staged_index,
    rollback_staged_index,
)


class Command(BaseCommand):
    help = "Pointer-flip promote (or --rollback restore) a staged per-document-set index version."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--index-version", type=int, required=True)
        parser.add_argument(
            "--rollback",
            action="store_true",
            help="Restore a superseded index version instead of promoting a promotable one.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        index = IndexVersion.objects.filter(pk=options["index_version"]).first()
        if index is None:
            raise CommandError("index version not found")
        try:
            if options["rollback"]:
                result = rollback_staged_index(index, actor=options["actor"])
                verb = "rolled back to"
            else:
                result = promote_staged_index(index, actor=options["actor"])
                verb = "promoted to"
        except StagedBuildError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"IndexVersion {result.pk} {verb} {result.status}"))
