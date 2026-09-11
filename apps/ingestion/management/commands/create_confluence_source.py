from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.documents.models import DocumentSet
from apps.ingestion.confluence_services import create_confluence_source
from apps.ingestion.models import ConfluenceProfile
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Create a tenant Confluence source bound to a granted profile and document set."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--organization", required=True)
        parser.add_argument("--document-set", required=True)
        parser.add_argument("--profile-id", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--root-page-id", action="append", required=True)
        parser.add_argument("--exclude-page-id", action="append", default=[])
        parser.add_argument("--exclude-roots", action="store_true")

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
            source = create_confluence_source(
                actor=actor,
                organization=organization,
                document_set=document_set,
                confluence_profile=profile,
                slug=options["slug"],
                name=options["name"],
                connector_config={
                    "root_page_ids": options["root_page_id"],
                    "include_root": not options["exclude_roots"],
                    "excluded_page_ids": options["exclude_page_id"],
                },
            )
        except (PermissionError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"created Confluence source {source.pk}"))
