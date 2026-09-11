from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.embedding_services import register_embedding_profile


class Command(BaseCommand):
    help = "Register an immutable platform EmbeddingProfile revision (platform admin only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--logical-id", required=True)
        parser.add_argument("--revision", type=int, required=True)
        parser.add_argument("--host", required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--secret-ref", required=True)
        parser.add_argument("--dimensions", type=int, required=True)
        parser.add_argument("--index-type", default="vector", choices=["vector", "halfvec"])
        parser.add_argument("--port", type=int, default=443)
        parser.add_argument("--path", default="/v1/embeddings")
        parser.add_argument("--no-normalize", action="store_true")
        parser.add_argument("--timeout-seconds", type=int, default=30)
        parser.add_argument("--max-response-bytes", type=int, default=5_000_000)
        parser.add_argument("--max-batch-size", type=int, default=64)

    def handle(self, *args: Any, **options: Any) -> None:
        user = get_user_model().objects.filter(username=options["actor"]).first()
        if user is None:
            raise CommandError("actor not found")
        try:
            profile = register_embedding_profile(
                actor=user,
                logical_id=options["logical_id"],
                revision=options["revision"],
                provider="openai_compatible",
                scheme="https",
                host=options["host"],
                port=options["port"],
                path=options["path"],
                model=options["model"],
                secret_ref=options["secret_ref"],
                dimensions=options["dimensions"],
                index_type=options["index_type"],
                normalize=not options["no_normalize"],
                distance_metric="cosine",
                timeout_seconds=options["timeout_seconds"],
                max_response_bytes=options["max_response_bytes"],
                max_batch_size=options["max_batch_size"],
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"registered EmbeddingProfile {profile.public_id}"))
