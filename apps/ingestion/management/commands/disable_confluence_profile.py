from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.confluence_services import disable_confluence_profile
from apps.ingestion.models import ConfluenceProfile


class Command(BaseCommand):
    help = "Disable an immutable Confluence profile revision."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--profile-id", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        profile = ConfluenceProfile.objects.filter(public_id=options["profile_id"]).first()
        if actor is None or profile is None:
            raise CommandError("actor or profile not found")
        try:
            disable_confluence_profile(actor=actor, confluence_profile=profile)
        except PermissionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Confluence profile disabled"))
