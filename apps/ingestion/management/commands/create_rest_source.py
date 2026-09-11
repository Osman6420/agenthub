from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.documents.models import DocumentSet
from apps.ingestion.models import RestPullContract, RestPullProfile
from apps.ingestion.rest_services import create_rest_source
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Create a tenant REST source bound to an exact profile, contract, and document set."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--document-set", required=True)
        parser.add_argument("--profile-id", required=True)
        parser.add_argument("--contract-id", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--inputs", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        organization = Organization.objects.filter(slug=options["organization"]).first()
        profile = RestPullProfile.objects.filter(public_id=options["profile_id"]).first()
        if actor is None or organization is None or profile is None:
            raise CommandError("actor, organization, document set, profile or contract not found")
        with transaction.atomic():
            set_tenant_context(organization.pk)
            document_set = DocumentSet.objects.filter(
                organization=organization, logical_id=options["document_set"]
            ).first()
            contract = RestPullContract.objects.filter(
                organization=organization, public_id=options["contract_id"]
            ).first()
        if document_set is None or contract is None:
            raise CommandError("actor, organization, document set, profile or contract not found")
        try:
            inputs = json.loads(Path(options["inputs"]).read_text(encoding="utf-8"))
            source = create_rest_source(
                actor=actor,
                organization=organization,
                document_set=document_set,
                rest_profile=profile,
                rest_contract=contract,
                slug=options["slug"],
                name=options["name"],
                inputs=inputs,
            )
        except (OSError, json.JSONDecodeError, PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"created REST source {source.pk}"))
