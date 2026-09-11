from __future__ import annotations

import os
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.ingestion.job_lifecycle import (
    CONTRACT_REVISION,
    compatible_worker_available,
    config_fingerprint,
)


class Command(BaseCommand):
    help = "Validate the non-secret ingestion role contract and report compatible-worker readiness."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument("--require-worker", action="store_true")  # type: ignore[attr-defined]

    def handle(self, *args: object, **options: object) -> None:
        problems: list[str] = []
        broker = urlsplit(str(settings.CELERY_BROKER_URL))
        object_store = settings.OBJECT_STORE
        endpoint = urlsplit(str(object_store.get("endpoint_url", "")))
        if broker.scheme not in {"redis", "rediss"}:
            problems.append("BROKER_SCHEME_UNSUPPORTED")
        if settings.DOCUMENTS_OBJECT_STORE_BACKEND == "s3":
            if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
                problems.append("OBJECT_STORE_ENDPOINT_INVALID")
            if not object_store.get("bucket"):
                problems.append("OBJECT_STORE_BUCKET_MISSING")
            if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get(
                "AWS_SECRET_ACCESS_KEY"
            ):
                problems.append("OBJECT_STORE_CREDENTIALS_MISSING")
        worker_ready = compatible_worker_available()
        if options["require_worker"] and not worker_ready:
            problems.append("COMPATIBLE_WORKER_UNAVAILABLE")
        if connection.vendor != "postgresql" and settings.DOCUMENTS_OBJECT_STORE_BACKEND == "s3":
            problems.append("POSTGRESQL_REQUIRED")
        if problems:
            raise CommandError(",".join(sorted(problems)))
        self.stdout.write(
            self.style.SUCCESS(
                "ingestion_preflight=ok "
                f"contract={CONTRACT_REVISION} "
                f"config={config_fingerprint()[:12]} "
                f"compatible_worker={'yes' if worker_ready else 'no'}"
            )
        )
