from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.embedding_services import grant_embedding_profile
from apps.ingestion.models import EmbeddingProfile
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Grant a platform EmbeddingProfile to one organization (platform admin only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True, help="organization slug")
        parser.add_argument("--profile-id", required=True, help="EmbeddingProfile public_id")

    def handle(self, *args: Any, **options: Any) -> None:
        user = get_user_model().objects.filter(username=options["actor"]).first()
        if user is None:
            raise CommandError("actor not found")
        organization = Organization.objects.filter(slug=options["organization"]).first()
        if organization is None:
            raise CommandError("organization not found")
        profile = EmbeddingProfile.objects.filter(public_id=options["profile_id"]).first()
        if profile is None:
            raise CommandError("embedding profile not found")
        try:
            grant_embedding_profile(
                actor=user, organization=organization, embedding_profile=profile
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"granted {profile.public_id} to {organization.slug}"))
