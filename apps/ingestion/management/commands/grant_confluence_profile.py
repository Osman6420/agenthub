from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.documents.models import DocumentSet
from apps.ingestion.confluence_services import grant_confluence_profile
from apps.ingestion.models import ConfluenceProfile
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Grant a Confluence profile to one tenant and exact document set."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--document-set", required=True)
        parser.add_argument("--profile-id", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        organization = Organization.objects.filter(slug=options["organization"]).first()
        document_set = DocumentSet.objects.filter(
            organization=organization, logical_id=options["document_set"]
        ).first()
        profile = ConfluenceProfile.objects.filter(public_id=options["profile_id"]).first()
        if actor is None or organization is None or document_set is None or profile is None:
            raise CommandError("actor, organization, document set or profile not found")
        try:
            grant_confluence_profile(
                actor=actor,
                organization=organization,
                document_set=document_set,
                confluence_profile=profile,
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Confluence profile granted"))
