from __future__ import annotations

import os
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import InterfaceError, OperationalError
from django.db.migrations.executor import MigrationExecutor

from apps.ingestion.embedding_services import register_embedding_profile
from apps.ingestion.models import EmbeddingProfile, EmbeddingProfileStatus
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.orchestration.services import register_model_profile

NOT_READY = 3


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CommandError(f"{name} is required")
    return value


def _required_int_env(name: str) -> int:
    value = _required_env(name)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise CommandError(f"{name} must be positive")
    return parsed


def _mismatched_fields(instance: Any, expected: dict[str, object]) -> list[str]:
    return sorted(name for name, value in expected.items() if getattr(instance, name) != value)


class Command(BaseCommand):
    help = "Create or verify the exact immutable deployment model and embedding profiles."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--check-only",
            action="store_true",
            help="Perform a read-only readiness check; missing state exits with status 3.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        check_only = bool(options["check_only"])
        try:
            self._handle(check_only=check_only)
        except (OperationalError, InterfaceError) as exc:
            raise CommandError("database is not reachable", returncode=NOT_READY) from exc

    def _handle(self, *, check_only: bool) -> None:
        from django.db import connection

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            raise CommandError(
                f"{len(pending)} database migrations are pending", returncode=NOT_READY
            )

        model_identity = {
            "logical_id": _required_env("MODEL_LOGICAL_ID"),
            "revision": _required_int_env("MODEL_REVISION"),
        }
        model_create_fields = {
            "provider": "openai_compatible",
            "scheme": "https",
            "host": _required_env("MODEL_HOST"),
            "port": _required_int_env("MODEL_PORT"),
            "path": _required_env("MODEL_PATH"),
            "model": _required_env("MODEL_NAME"),
            "secret_ref": "secret:primary",
            "timeout_seconds": 30,
            "max_response_bytes": 1_000_000,
            "max_output_tokens": 2048,
        }
        model_expected = {**model_create_fields, "status": ModelProfileStatus.ACTIVE}
        embedding_identity = {
            "logical_id": _required_env("EMBEDDING_LOGICAL_ID"),
            "revision": _required_int_env("EMBEDDING_REVISION"),
        }
        embedding_create_fields = {
            "provider": "openai_compatible",
            "scheme": "https",
            "host": _required_env("EMBEDDING_HOST"),
            "port": _required_int_env("EMBEDDING_PORT"),
            "path": _required_env("EMBEDDING_PATH"),
            "model": _required_env("EMBEDDING_NAME"),
            "secret_ref": "secret:primary",
            "dimensions": _required_int_env("EMBEDDING_DIMENSIONS"),
            "index_type": _required_env("EMBEDDING_INDEX_TYPE"),
            "normalize": True,
            "distance_metric": "cosine",
            "timeout_seconds": 30,
            "max_response_bytes": 5_000_000,
            "max_batch_size": 64,
        }
        embedding_expected = {
            **embedding_create_fields,
            "status": EmbeddingProfileStatus.ACTIVE,
        }

        model_profile = ModelProfile.objects.filter(**model_identity).first()
        embedding_profile = EmbeddingProfile.objects.filter(**embedding_identity).first()
        missing = []
        if model_profile is None:
            missing.append("model")
        else:
            mismatches = _mismatched_fields(model_profile, model_expected)
            if mismatches:
                raise CommandError(
                    "existing model profile does not match deployment fields: "
                    + ", ".join(mismatches)
                )
        if embedding_profile is None:
            missing.append("embedding")
        else:
            mismatches = _mismatched_fields(embedding_profile, embedding_expected)
            if mismatches:
                raise CommandError(
                    "existing embedding profile does not match deployment fields: "
                    + ", ".join(mismatches)
                )

        if check_only:
            if missing:
                raise CommandError(
                    "deployment profiles are missing: " + ", ".join(missing),
                    returncode=NOT_READY,
                )
            self.stdout.write("database migrations and deployment profiles are ready")
            return

        actor_name = _required_env("PLATFORM_ACTOR")
        actor = get_user_model().objects.filter(username=actor_name).first()
        if actor is None:
            raise CommandError("platform actor not found")
        try:
            if model_profile is None:
                register_model_profile(actor=actor, **model_identity, **model_create_fields)
            if embedding_profile is None:
                register_embedding_profile(
                    actor=actor,
                    **embedding_identity,
                    **embedding_create_fields,
                )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("deployment profiles are ready"))
