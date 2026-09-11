"""Preview is the default; never scan or purge all tenants implicitly."""

import json
from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.rest_setup_retention import RestSetupRetentionError, purge_expired_setup_drafts


class Command(BaseCommand):
    help = "Preview expired private REST setup content; --apply irreversibly clears one batch."

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = purge_expired_setup_drafts(
                organization_id=options["organization_id"],
                actor=options["actor"],
                batch_size=options["batch_size"],
                apply=options["apply"],
            )
        except RestSetupRetentionError as exc:
            raise CommandError(exc.code) from None
        self.stdout.write(json.dumps(asdict(result), sort_keys=True))
