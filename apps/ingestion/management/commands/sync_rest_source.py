from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import Source
from apps.ingestion.rest_services import create_rest_sync_run
from apps.ingestion.tasks import sync_rest_source


class Command(BaseCommand):
    help = "Queue a governed generic REST source snapshot sync."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--source", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        source = Source.objects.filter(
            organization__slug=options["organization"], slug=options["source"]
        ).first()
        if actor is None or source is None:
            raise CommandError("actor or source not found")
        try:
            run = create_rest_sync_run(actor=actor, source=source)
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        sync_rest_source.apply_async(args=[run.pk, source.organization_id], queue="ingestion")
        self.stdout.write(self.style.SUCCESS(f"queued REST sync run {run.pk}"))
