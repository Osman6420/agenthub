from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Scenario
from apps.ingestion.models import EmbeddingProfile, Source
from apps.ingestion.rest_services import configure_sync_schedule
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Configure periodic connector refresh and optional gated on-change automation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--source", required=True)
        parser.add_argument("--interval-seconds", type=int, required=True)
        parser.add_argument("--enable", action="store_true")
        parser.add_argument(
            "--automation-mode",
            choices=["draft_only", "stage_only", "promote_if_safe"],
            default="draft_only",
        )
        parser.add_argument("--embedding-profile-id")
        parser.add_argument(
            "--scenario",
            action="append",
            default=[],
            metavar="PROJECT_SLUG/SCENARIO_SLUG",
            help="Exact promotion target; repeat for multiple targets.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        organization = Organization.objects.filter(slug=options["organization"]).first()
        profile = (
            EmbeddingProfile.objects.filter(public_id=options["embedding_profile_id"]).first()
            if options["embedding_profile_id"]
            else None
        )
        if actor is None or organization is None:
            raise CommandError("actor, source or scenario not found")
        target_keys: list[tuple[str, str]] = []
        for value in options["scenario"]:
            parts = value.split("/")
            if len(parts) != 2 or not all(parts):
                raise CommandError("scenario must use PROJECT_SLUG/SCENARIO_SLUG")
            target_keys.append((parts[0], parts[1]))
        if len(target_keys) != len(set(target_keys)):
            raise CommandError("duplicate scenario target")
        with transaction.atomic():
            set_tenant_context(organization.pk)
            source = Source.objects.filter(
                organization=organization, slug=options["source"]
            ).first()
            scenarios = [
                Scenario.objects.select_related("project")
                .filter(
                    project__organization=organization,
                    project__slug=project_slug,
                    slug=scenario_slug,
                )
                .first()
                for project_slug, scenario_slug in target_keys
            ]
        if source is None or any(scenario is None for scenario in scenarios):
            raise CommandError("actor, source or scenario not found")
        exact_scenarios = [cast(Scenario, scenario) for scenario in scenarios]
        try:
            schedule = configure_sync_schedule(
                actor=actor,
                source=source,
                interval_seconds=options["interval_seconds"],
                enabled=options["enable"],
                next_run_at=timezone.now() + timedelta(seconds=options["interval_seconds"]),
                automation_mode=options["automation_mode"],
                embedding_profile=profile,
                scenarios=exact_scenarios,
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"configured connector schedule {schedule.pk}"))
