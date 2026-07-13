from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.documents.models import DocumentSet
from apps.ingestion.models import RestPullProfile
from apps.ingestion.rest_services import grant_rest_profile
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Grant one REST profile to an exact tenant document set."

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
        profile = RestPullProfile.objects.filter(public_id=options["profile_id"]).first()
        if actor is None or organization is None or document_set is None or profile is None:
            raise CommandError("actor, organization, document set or profile not found")
        try:
            grant_rest_profile(
                actor=actor,
                organization=organization,
                document_set=document_set,
                rest_profile=profile,
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("REST profile grant created"))
