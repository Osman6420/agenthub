from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.documents.models import DocumentSet
from apps.ingestion.rest_services import create_rest_contract
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Create one immutable tenant generic REST pull-contract revision from JSON."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--document-set", required=True)
        parser.add_argument("--logical-id", required=True)
        parser.add_argument("--revision", type=int, required=True)
        parser.add_argument("--definition", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        organization = Organization.objects.filter(slug=options["organization"]).first()
        document_set = DocumentSet.objects.filter(
            organization=organization,
            logical_id=options["document_set"],
        ).first()
        if actor is None or organization is None or document_set is None:
            raise CommandError("actor, organization, or document set not found")
        try:
            definition = json.loads(Path(options["definition"]).read_text(encoding="utf-8"))
            contract = create_rest_contract(
                actor=actor,
                organization=organization,
                document_set=document_set,
                logical_id=options["logical_id"],
                revision=options["revision"],
                definition=definition,
            )
        except (OSError, json.JSONDecodeError, PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"created RestPullContract {contract.public_id}"))
