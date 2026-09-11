"""Explicit operator command; no scheduler or implicit tenant sweep."""

import json
from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.shared_retention import reclaim_shared_generation
from apps.ingestion.vector_store import VectorStoreError


class Command(BaseCommand):
    help = "Preview old unreferenced shared data; --apply deletes at most one chunk batch."

    def add_arguments(self, parser):
        parser.add_argument("index_id", type=int)
        parser.add_argument("--organization-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = reclaim_shared_generation(
                organization_id=options["organization_id"],
                index_version_id=options["index_id"],
                actor=options["actor"],
                batch_size=options["batch_size"],
                apply=options["apply"],
            )
        except VectorStoreError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(asdict(result), sort_keys=True))
