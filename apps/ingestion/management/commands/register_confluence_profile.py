from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.confluence_services import register_confluence_profile


class Command(BaseCommand):
    help = "Register an immutable platform Confluence Data Center profile revision."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--logical-id", required=True)
        parser.add_argument("--revision", type=int, required=True)
        parser.add_argument("--base-url", required=True)
        parser.add_argument("--secret-ref", required=True)
        parser.add_argument("--network-policy-id", required=True)
        parser.add_argument("--timeout-seconds", type=int, default=30)
        parser.add_argument("--page-size", type=int, default=50)
        parser.add_argument("--max-pages", type=int, default=5_000)
        parser.add_argument("--max-depth", type=int, default=50)
        parser.add_argument("--max-requests", type=int, default=20_000)
        parser.add_argument("--max-retries", type=int, default=2)
        parser.add_argument("--max-response-bytes", type=int, default=5_000_000)
        parser.add_argument("--max-page-body-bytes", type=int, default=4_000_000)
        parser.add_argument("--max-total-bytes", type=int, default=100_000_000)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("actor not found")
        try:
            profile = register_confluence_profile(
                actor=actor,
                base_url=options["base_url"],
                logical_id=options["logical_id"],
                revision=options["revision"],
                secret_ref=options["secret_ref"],
                network_policy_id=options["network_policy_id"],
                timeout_seconds=options["timeout_seconds"],
                page_size=options["page_size"],
                max_pages=options["max_pages"],
                max_depth=options["max_depth"],
                max_requests=options["max_requests"],
                max_retries=options["max_retries"],
                max_response_bytes=options["max_response_bytes"],
                max_page_body_bytes=options["max_page_body_bytes"],
                max_total_bytes=options["max_total_bytes"],
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"registered ConfluenceProfile {profile.public_id}"))
