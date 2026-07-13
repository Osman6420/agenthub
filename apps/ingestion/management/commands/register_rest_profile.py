from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.rest_services import register_rest_profile


class Command(BaseCommand):
    help = "Register an immutable platform-governed generic REST pull profile."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--logical-id", required=True)
        parser.add_argument("--revision", type=int, required=True)
        parser.add_argument("--base-url", required=True)
        parser.add_argument("--path-prefix", required=True)
        parser.add_argument("--method", choices=["GET", "POST"], default="GET")
        parser.add_argument(
            "--auth-mode", choices=["none", "bearer", "api_key_header"], default="none"
        )
        parser.add_argument("--secret-ref", default="")
        parser.add_argument("--api-key-header-name", default="")
        parser.add_argument("--timeout-seconds", type=int, default=30)
        parser.add_argument("--max-response-bytes", type=int, default=5_000_000)
        parser.add_argument("--max-total-bytes", type=int, default=100_000_000)
        parser.add_argument("--max-requests", type=int, default=1_000)
        parser.add_argument("--max-items", type=int, default=50_000)
        parser.add_argument("--max-pages", type=int, default=1_000)
        parser.add_argument("--max-retries", type=int, default=2)
        parser.add_argument("--max-decoded-item-bytes", type=int, default=25_000_000)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("actor not found")
        try:
            profile = register_rest_profile(
                actor=actor,
                base_url=options["base_url"],
                path_prefix=options["path_prefix"],
                logical_id=options["logical_id"],
                revision=options["revision"],
                method=options["method"],
                auth_mode=options["auth_mode"],
                secret_ref=options["secret_ref"],
                api_key_header_name=options["api_key_header_name"],
                timeout_seconds=options["timeout_seconds"],
                max_response_bytes=options["max_response_bytes"],
                max_total_bytes=options["max_total_bytes"],
                max_requests=options["max_requests"],
                max_items=options["max_items"],
                max_pages=options["max_pages"],
                max_retries=options["max_retries"],
                max_decoded_item_bytes=options["max_decoded_item_bytes"],
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"registered RestPullProfile {profile.public_id}"))
