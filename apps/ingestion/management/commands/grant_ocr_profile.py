from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import OcrProfile
from apps.ingestion.ocr_services import grant_ocr_profile
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Grant a platform OCR profile to one organization."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True, help="Organization slug")
        parser.add_argument("--profile-id", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        organization = Organization.objects.filter(slug=options["organization"]).first()
        profile = OcrProfile.objects.filter(public_id=options["profile_id"]).first()
        if actor is None or organization is None or profile is None:
            raise CommandError("actor, organization or OCR profile not found")
        try:
            grant_ocr_profile(actor=actor, organization=organization, ocr_profile=profile)
        except PermissionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("OCR profile granted"))
