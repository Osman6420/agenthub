from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import IngestionRun, RunStatus
from apps.ingestion.services import create_run
from apps.ingestion.tasks import ingest_source


class Command(BaseCommand):
    help = "Create a new ingestion attempt for a dead-lettered run."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--run", required=True, type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        previous = IngestionRun.objects.select_related("source").filter(pk=options["run"]).first()
        if previous is None or previous.status != RunStatus.DEAD_LETTER:
            raise CommandError("run must exist and be dead-lettered")
        run = create_run(source=previous.source, max_attempts=previous.max_attempts)
        ingest_source.delay(run.pk, run.organization_id)
        self.stdout.write(self.style.SUCCESS(f"queued retry run {run.pk}"))
