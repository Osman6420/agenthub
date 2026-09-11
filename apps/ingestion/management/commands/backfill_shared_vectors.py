"""Explicit owner-operated bounded import; preview is the default."""

import json
from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.shared_backfill import backfill_generation
from apps.ingestion.vector_store import VectorStoreError


class Command(BaseCommand):
    help = "Preview or import one batch of a stable index after compatible worker drain."

    def add_arguments(self, parser):
        parser.add_argument("index_version_id", type=int)
        parser.add_argument("--organization-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        try:
            result = backfill_generation(
                index_version_id=options["index_version_id"],
                organization_id=options["organization_id"],
                actor=options["actor"],
                apply=options["apply"],
                batch_size=options["batch_size"],
            )
        except VectorStoreError as exc:
            raise CommandError(exc.code) from None
        self.stdout.write(json.dumps(asdict(result), sort_keys=True))
