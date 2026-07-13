from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.confluence_services import create_confluence_sync_run
from apps.ingestion.models import ConnectorType, Source
from apps.ingestion.tasks import sync_confluence_source


class Command(BaseCommand):
    help = "Queue an authorized Confluence source synchronization."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--source", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        source = Source.objects.filter(
            organization__slug=options["organization"],
            slug=options["source"],
            connector_type=ConnectorType.CONFLUENCE_DC,
        ).first()
        if actor is None or source is None:
            raise CommandError("actor or Confluence source not found")
        try:
            run = create_confluence_sync_run(actor=actor, source=source)
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        sync_confluence_source.delay(run.pk, run.organization_id)
        self.stdout.write(self.style.SUCCESS(f"queued Confluence sync run {run.pk}"))
