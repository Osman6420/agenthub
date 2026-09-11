"""Issue a bearer token for a consumer. The plaintext is printed once."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.identity.credentials import CredentialLifecycleError, issue_consumer_token
from apps.identity.models import Consumer


class Command(BaseCommand):
    help = "Create a bearer token for a consumer (plaintext shown once)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organization", required=True, help="Organization slug.")
        parser.add_argument("--subject", required=True, help="Consumer subject.")
        parser.add_argument("--name", default="cli-issued", help="Token name/label.")
        parser.add_argument("--actor", default="cli")

    def handle(self, *args: Any, **options: Any) -> None:
        consumer = (
            Consumer.objects.select_related("organization")
            .filter(organization__slug=options["organization"], subject=options["subject"])
            .first()
        )
        if consumer is None:
            raise CommandError(
                f"consumer not found: {options['organization']}/{options['subject']}"
            )

        try:
            _token, raw = issue_consumer_token(
                consumer=consumer,
                name=options["name"],
                actor_id=options["actor"],
            )
        except CredentialLifecycleError as exc:
            raise CommandError(exc.code) from exc
        self.stdout.write(self.style.SUCCESS("Token created (store it now; shown once):"))
        self.stdout.write(raw)
