"""Issue a bearer token for a consumer. The plaintext is printed once."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.audit.services import record_event
from apps.identity.models import Consumer
from apps.identity.tokens import create_token


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

        token, raw = create_token(consumer, options["name"])
        record_event(
            actor_type="user",
            actor_id=options["actor"],
            action="consumer_token.create",
            outcome="success",
            organization_id=consumer.organization_id,
            resource_type="consumer_token",
            resource_id=str(token.pk),
            reason=token.prefix,
        )
        self.stdout.write(self.style.SUCCESS("Token created (store it now; shown once):"))
        self.stdout.write(raw)
