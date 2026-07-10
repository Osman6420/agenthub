from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import Source
from apps.ingestion.services import IngestionError, create_run
from apps.ingestion.tasks import ingest_source


class Command(BaseCommand):
    help = "Queue ingestion for an active source identified by organization/slug."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True)
        parser.add_argument("--source", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        source = Source.objects.filter(
            organization__slug=options["organization"], slug=options["source"]
        ).first()
        if source is None:
            raise CommandError("unknown source in organization")
        try:
            run = create_run(source=source)
        except IngestionError as exc:
            raise CommandError(exc.code) from exc
        ingest_source.delay(run.pk)
        self.stdout.write(self.style.SUCCESS(f"queued ingestion run {run.pk}"))
