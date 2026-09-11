"""Report or purge bulky orchestration state past the 90-day window (P2.6.11).

Report mode is the default and mutates nothing; it prints eligible counts per retention
class. ``--commit`` performs the bounded, audited, fail-closed purge and is restricted to a
Django superuser (``platform_admin``), and only after owner window approval. Purge clears
named bulky columns (agent checkpoints, branch working state, wait correlation material) and
never deletes rows, audit records, eval evidence or lineage metadata.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.observability.retention import DEFAULT_BATCH_SIZE, run_retention
from apps.tenancy.services import is_platform_admin


class Command(BaseCommand):
    help = "Report (default) or purge bulky orchestration state older than 90 days."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Perform the purge. Without this flag the command only reports.",
        )
        parser.add_argument(
            "--actor",
            default="",
            help="Django username of the platform admin (required with --commit).",
        )
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    def handle(self, *args: Any, **options: Any) -> None:
        commit = bool(options["commit"])
        actor = str(options.get("actor") or "")
        if commit:
            if not actor:
                raise CommandError("--actor is required with --commit")
            user = get_user_model().objects.filter(username=actor).first()
            if user is None or not is_platform_admin(user):
                raise CommandError("purge denied: actor is not a platform admin")

        reports = run_retention(
            commit=commit,
            batch_size=int(options["batch_size"]),
            actor=actor or "retention-job",
        )
        mode = "COMMIT" if commit else "REPORT"
        self.stdout.write(f"Retention {mode} (window: 90 days)")
        for report in reports:
            self.stdout.write(
                f"  {report.retention_class}: eligible={report.eligible} purged={report.purged}"
            )
