from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.ocr_services import register_ocr_profile


class Command(BaseCommand):
    help = "Register an immutable platform OCR profile revision."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--logical-id", required=True)
        parser.add_argument("--revision", type=int, required=True)
        parser.add_argument("--host", required=True)
        parser.add_argument("--secret-ref", required=True)
        parser.add_argument("--port", type=int, default=443)
        parser.add_argument("--base-path", default="/api/v1")
        parser.add_argument("--timeout-seconds", type=int, default=30)
        parser.add_argument("--poll-interval-seconds", type=int, default=2)
        parser.add_argument("--max-poll-attempts", type=int, default=150)
        parser.add_argument("--max-upload-bytes", type=int, default=52_428_800)
        parser.add_argument("--max-pages", type=int, default=500)
        parser.add_argument("--max-result-bytes", type=int, default=10_000_000)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("actor not found")
        try:
            profile = register_ocr_profile(
                actor=actor,
                logical_id=options["logical_id"],
                revision=options["revision"],
                provider="async_markdown_ocr",
                scheme="https",
                host=options["host"],
                port=options["port"],
                base_path=options["base_path"],
                secret_ref=options["secret_ref"],
                timeout_seconds=options["timeout_seconds"],
                poll_interval_seconds=options["poll_interval_seconds"],
                max_poll_attempts=options["max_poll_attempts"],
                max_upload_bytes=options["max_upload_bytes"],
                max_pages=options["max_pages"],
                max_result_bytes=options["max_result_bytes"],
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"registered OcrProfile {profile.public_id}"))
