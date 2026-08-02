"""Seed deterministic synthetic role fixtures into a guarded browser-gate database."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.documents import services as document_services
from apps.documents.models import DocumentSet, DocumentSetVersionStatus
from apps.identity.models import (
    Consumer,
    ConsumerToken,
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.tokens import hash_token
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
PASSWORD = "phase-2-9-browser-only"  # noqa: S105
REST_TOKEN = "phase-2-9-browser-rest-token"  # noqa: S105


class Command(BaseCommand):
    help = "Seed Phase 2.9 synthetic browser role fixtures (guarded settings only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings.browser_gate":
            raise CommandError("browser fixture seeding requires guarded browser_gate settings")
        fixture_path = os.environ.get("BROWSER_GATE_FIXTURE_PATH", "").strip()
        if not fixture_path:
            raise CommandError("BROWSER_GATE_FIXTURE_PATH is required")

        call_command(
            "seed_demo",
            password=PASSWORD,
            no_print_secrets=True,
            verbosity=0,
        )
        organization = Organization.objects.get(slug="demo")
        scenarios = list(Scenario.objects.filter(organization=organization).order_by("slug"))
        primary = next(item for item in scenarios if item.slug == "empty-workflow")
        sibling = next(item for item in scenarios if item.slug == "document-answer")

        viewer = self._member("viewer-browser", organization)
        runtime = self._member("runtime-browser", organization)
        content_reader = self._member("content-browser", organization)
        document_manager = self._member("document-manager-browser", organization)
        unassigned = self._member("unassigned-browser", organization)
        admin = User.objects.get(username="admin")
        self._scenario_duty(viewer, primary, ScenarioResponsibility.VIEWER, admin)
        self._scenario_duty(runtime, primary, ScenarioResponsibility.RUNTIME_OPERATOR, admin)
        rest_consumer = Consumer.objects.get(organization=organization, subject="demo-client")
        ConsumerToken.objects.create(
            organization=organization,
            consumer=rest_consumer,
            name="browser-gate",
            prefix=REST_TOKEN[:8],
            token_hash=hash_token(REST_TOKEN),
        )

        document_set = DocumentSet.objects.create(
            organization=organization,
            logical_id="browser-policies",
            name="Browser Policies",
        )
        draft = document_services.get_or_create_manual_draft(
            document_set=document_set, actor="browser-seed"
        )
        version = document_services.upload_document(
            organization=organization,
            logical_id="browser-policy",
            title="Browser policy",
            mime_type="text/plain",
            data=b"Synthetic browser gate policy.",
            actor="browser-seed",
            document_set_version=draft,
        )
        content_membership = OrganizationMembership.objects.get(
            organization=organization, user=content_reader
        )
        DocumentSetResponsibilityAssignment.objects.create(
            organization=organization,
            membership=content_membership,
            document_set=document_set,
            responsibility=DocumentSetResponsibility.CONTENT_READER,
            assigned_by=admin,
        )
        manager_membership = OrganizationMembership.objects.get(
            organization=organization, user=document_manager
        )
        DocumentSetResponsibilityAssignment.objects.create(
            organization=organization,
            membership=manager_membership,
            document_set=document_set,
            responsibility=DocumentSetResponsibility.MANAGER,
            assigned_by=admin,
        )
        retrieval_profile = create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.RETRIEVAL_PROFILE,
            logical_id="browser-retrieval",
            body={
                "api_version": "agenthub/retrieval/v1",
                "kind": "RetrievalProfile",
                "mode": "hybrid",
                "top_k": 5,
                "score_threshold": 0.0,
                "vector_weight": 0.6,
                "keyword_weight": 0.4,
            },
            created_by="browser-seed",
        )
        index = IndexVersion.objects.create(
            organization=organization,
            document_set_version=draft,
            retrieval_profile=retrieval_profile,
            version=1,
            status=IndexStatus.ACTIVE,
            store_ready=True,
            document_count=1,
            chunk_count=1,
        )
        draft.status = DocumentSetVersionStatus.ACTIVE
        draft.built_index_version = index
        draft.save(update_fields=["status", "built_index_version", "updated_at"])

        foreign_org = Organization.objects.create(slug="foreign-browser", name="Foreign Browser")
        foreign_project = AIProject.objects.create(
            organization=foreign_org, slug="foreign", name="Foreign"
        )
        foreign_scenario = Scenario.objects.create(
            project=foreign_project, slug="foreign", name="Foreign scenario"
        )
        foreign_user = self._member("foreign-browser", foreign_org)
        foreign_admin = foreign_user
        self._scenario_duty(
            foreign_user, foreign_scenario, ScenarioResponsibility.VIEWER, foreign_admin
        )

        fixture = {
            "users": {
                "admin": "admin",
                "editor": "editor",
                "releaser": "releaser",
                "viewer": viewer.username,
                "runtime": runtime.username,
                "content_reader": content_reader.username,
                "document_manager": document_manager.username,
                "unassigned": unassigned.username,
                "foreign": foreign_user.username,
            },
            "primary_scenario": str(primary.public_id),
            "sibling_scenario": str(sibling.public_id),
            "foreign_scenario": str(foreign_scenario.public_id),
            "document_set": str(document_set.public_id),
            "document": str(version.document.public_id),
            "document_version": version.pk,
        }
        target = Path(fixture_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fixture, sort_keys=True), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS("Phase 2.9 browser fixture ready."))

    @staticmethod
    def _member(username: str, organization: Organization) -> Any:
        user = User.objects.create_user(username=username, password=PASSWORD)
        OrganizationMembership.objects.create(organization=organization, user=user)
        return user

    @staticmethod
    def _scenario_duty(user: Any, scenario: Scenario, responsibility: str, actor: Any) -> None:
        membership = OrganizationMembership.objects.get(
            organization=scenario.organization, user=user
        )
        ScenarioResponsibilityAssignment.objects.create(
            organization=scenario.organization,
            membership=membership,
            scenario=scenario,
            responsibility=responsibility,
            assigned_by=actor,
        )
