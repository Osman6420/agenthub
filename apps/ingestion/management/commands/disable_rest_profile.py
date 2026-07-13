from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import RestPullProfile
from apps.ingestion.rest_services import disable_rest_profile


class Command(BaseCommand):
    help = "Disable an immutable generic REST pull-profile revision."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--profile-id", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        profile = RestPullProfile.objects.filter(public_id=options["profile_id"]).first()
        if actor is None or profile is None:
            raise CommandError("actor or profile not found")
        try:
            disable_rest_profile(actor=actor, rest_profile=profile)
        except PermissionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("REST pull profile disabled"))
