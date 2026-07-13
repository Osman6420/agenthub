"""P9.3 set-scoped connector source, mapping, schedule and run controls."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.services import bind_scenario_document_set, create_document_set
from apps.identity.roles import Role
from apps.ingestion.models import (
    ConfluenceProfile,
    ConnectorSyncSchedule,
    ConnectorType,
    EmbeddingProfile,
    RestPullContract,
    RestPullProfile,
    RestSyncRun,
    ScheduleAutomationMode,
    Source,
    TenantConfluenceProfileGrant,
    TenantEmbeddingProfileGrant,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest_services import create_rest_contract, create_rest_source
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


def _member(username: str, org: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


def _definition() -> dict[str, Any]:
    return {
        "version": 1,
        "inputs": {"dataset": {"type": "string", "max_length": 64}},
        "request": {
            "method": "GET",
            "path": "/documents/{input:dataset}",
            "query": {},
        },
        "response": {
            "items_pointer": "/data/items",
            "id_pointer": "/id",
            "revision_pointer": "/revision",
            "title_pointer": "/title",
            "content_pointer": "/content",
            "content_encoding": "utf8_text",
            "mime_type": "text/markdown",
        },
        "pagination": {"mode": "none"},
    }


def _confluence_profile(logical_id: str = "corp-wiki") -> ConfluenceProfile:
    return ConfluenceProfile.objects.create(
        logical_id=logical_id,
        revision=1,
        host="confluence.private.example",
        context_path="/confluence",
        secret_ref="secret:confluence-reader",  # noqa: S106 -- opaque reference
        network_policy_id="private-confluence",
        created_by="platform",
    )


def _rest_profile(logical_id: str = "knowledge-api") -> RestPullProfile:
    return RestPullProfile.objects.create(
        logical_id=logical_id,
        revision=1,
        host="rest.private.example",
        path_prefix="/api/v1",
        secret_ref="secret:rest-reader",  # noqa: S106 -- opaque reference
        created_by="platform",
    )


def _embedding_profile(org: Organization) -> EmbeddingProfile:
    profile = EmbeddingProfile.objects.create(
        logical_id="embed",
        revision=1,
        host="embedding.private.example",
        model="embed-v1",
        secret_ref="secret:embedding",  # noqa: S106 -- opaque reference
        dimensions=64,
        created_by="platform",
    )
    TenantEmbeddingProfileGrant.objects.create(
        organization=org, embedding_profile=profile, created_by="platform"
    )
    return profile


def _rest_source(org: Organization, document_set: Any, actor: Any) -> Source:
    profile = _rest_profile()
    TenantRestPullProfileGrant.objects.create(
        organization=org,
        document_set=document_set,
        rest_profile=profile,
        created_by="platform",
    )
    contract = create_rest_contract(
        actor=actor,
        organization=org,
        logical_id="documents",
        revision=1,
        definition=_definition(),
    )
    return create_rest_source(
        actor=actor,
        organization=org,
        document_set=document_set,
        rest_profile=profile,
        rest_contract=contract,
        slug="rest-documents",
        name="REST Documents",
        inputs={"dataset": "finance-private-input"},
    )


@pytest.mark.django_db
def test_connector_workspace_redacts_authority_and_input_values(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    author = _member("author", org, Role.SCENARIO_EDITOR)
    profile = _confluence_profile()
    TenantConfluenceProfileGrant.objects.create(
        organization=org,
        document_set=document_set,
        confluence_profile=profile,
        created_by="platform",
    )
    Source.objects.create(
        organization=org,
        document_set=document_set,
        confluence_profile=profile,
        connector_type=ConnectorType.CONFLUENCE_DC,
        connector_config={"root_page_ids": ["123"], "include_root": True, "excluded_page_ids": []},
        slug="wiki",
        name="Wiki",
    )
    _rest_source(org, document_set, author)

    client.force_login(author)
    response = client.get(reverse("console:document_set_connectors", args=[document_set.pk]))
    body = response.content.decode()
    assert response.status_code == 200
    assert "corp-wiki · r1" in body and "knowledge-api · r1" in body
    for denied in (
        "confluence.private.example",
        "rest.private.example",
        "secret:confluence-reader",
        "secret:rest-reader",
        "finance-private-input",
    ):
        assert denied not in body


@pytest.mark.django_db
def test_rest_contract_preview_is_bounded_metadata_only_and_no_egress(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("author", org, Role.SCENARIO_EDITOR))
    payload = {
        "contract-logical_id": "documents",
        "contract-revision": "1",
        "contract-definition": json.dumps(_definition()),
        "contract-synthetic_response": json.dumps(
            {
                "data": {
                    "items": [
                        {
                            "id": "doc-1",
                            "revision": "7",
                            "title": "Policy",
                            "content": "SYNTHETIC_SECRET_CONTENT",
                        }
                    ]
                }
            }
        ),
    }
    with patch("apps.tools.http_adapter.perform_bounded_https_request") as egress:
        response = client.post(
            reverse("console:rest_contract_preview", args=[document_set.pk]), payload
        )
        egress.assert_not_called()
    body = response.content.decode()
    assert response.status_code == 200
    assert "doc-1" in body and "Policy" in body
    assert "SYNTHETIC_SECRET_CONTENT" not in body
    assert RestPullContract.objects.count() == 0

    preview = json.loads(payload["contract-synthetic_response"])
    preview["data"]["items"] = preview["data"]["items"] * 21
    payload["contract-synthetic_response"] = json.dumps(preview)
    denied = client.post(reverse("console:rest_contract_preview", args=[document_set.pk]), payload)
    assert "REST_PREVIEW_ITEMS_INVALID" in denied.content.decode()


@pytest.mark.django_db
def test_confluence_source_requires_exact_set_grant_and_author(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    other_set = create_document_set(
        organization=org, logical_id="other", name="Other", actor="seed"
    )
    author = _member("author", org, Role.SCENARIO_EDITOR)
    profile = _confluence_profile()
    TenantConfluenceProfileGrant.objects.create(
        organization=org,
        document_set=other_set,
        confluence_profile=profile,
        created_by="platform",
    )
    url = reverse("console:confluence_source_create", args=[document_set.pk])
    payload = {
        "confluence-confluence_profile": str(profile.pk),
        "confluence-slug": "wiki",
        "confluence-name": "Wiki",
        "confluence-root_page_ids": "123\n456",
        "confluence-excluded_page_ids": "789",
        "confluence-include_root": "on",
    }
    client.force_login(author)
    assert client.post(url, payload).status_code == 302
    assert not Source.objects.filter(slug="wiki").exists()

    TenantConfluenceProfileGrant.objects.create(
        organization=org,
        document_set=document_set,
        confluence_profile=profile,
        created_by="platform",
    )
    assert client.post(url, payload).status_code == 302
    source = Source.objects.get(slug="wiki")
    assert source.connector_config["root_page_ids"] == ["123", "456"]
    assert AuditEvent.objects.filter(action="confluence_source.create").exists()

    client.force_login(_member("auditor", org, Role.AUDITOR))
    assert client.post(url, payload).status_code == 403


@pytest.mark.django_db
def test_rest_contract_source_and_cross_tenant_routes_fail_closed(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    foreign_set = create_document_set(
        organization=other, logical_id="foreign", name="Foreign", actor="seed"
    )
    author = _member("author", org, Role.PROJECT_OWNER)
    profile = _rest_profile()
    TenantRestPullProfileGrant.objects.create(
        organization=org,
        document_set=document_set,
        rest_profile=profile,
        created_by="platform",
    )
    client.force_login(author)
    contract_payload = {
        "contract-logical_id": "documents",
        "contract-revision": "1",
        "contract-definition": json.dumps(_definition()),
        "contract-synthetic_response": "",
    }
    response = client.post(
        reverse("console:rest_contract_create", args=[document_set.pk]), contract_payload
    )
    assert response.status_code == 302
    contract = RestPullContract.objects.get(logical_id="documents")
    source_payload = {
        "rest-source-rest_profile": str(profile.pk),
        "rest-source-rest_contract": str(contract.pk),
        "rest-source-slug": "rest-docs",
        "rest-source-name": "REST Docs",
        "rest-source-inputs": json.dumps({"dataset": "policies"}),
    }
    source_url = reverse("console:rest_source_create", args=[document_set.pk])
    assert client.post(source_url, source_payload).status_code == 302
    assert Source.objects.filter(slug="rest-docs", organization=org).exists()
    foreign_url = reverse("console:document_set_connectors", args=[foreign_set.pk])
    assert client.get(foreign_url).status_code == 404


@pytest.mark.django_db
def test_run_now_queues_ids_only_and_dispatch_failure_is_terminal(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    author = _member("author", org, Role.SCENARIO_EDITOR)
    source = _rest_source(org, document_set, author)
    client.force_login(author)
    url = reverse("console:connector_source_run", args=[source.pk])

    with patch("apps.console.views.sync_rest_source.apply_async") as enqueue:
        assert client.post(url).status_code == 302
        run = RestSyncRun.objects.latest("pk")
        enqueue.assert_called_once_with(args=[run.pk, org.pk], queue="ingestion")
        assert "secret" not in str(enqueue.call_args).lower()
        assert "private.example" not in str(enqueue.call_args)

    with patch(
        "apps.console.views.sync_rest_source.apply_async", side_effect=RuntimeError("broker down")
    ):
        assert client.post(url).status_code == 302
    failed = RestSyncRun.objects.latest("pk")
    assert failed.status == "dead_letter"
    assert failed.error_code == "BROKER_UNAVAILABLE"
    assert AuditEvent.objects.filter(action="rest_sync.dispatch_failed").exists()


@pytest.mark.django_db
def test_schedule_role_split_and_bound_promotion_target(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    author = _member("author", org, Role.SCENARIO_EDITOR)
    source = _rest_source(org, document_set, author)
    embedding = _embedding_profile(org)
    project = AIProject.objects.create(
        organization=org, slug="assistant", name="Assistant", owner="author"
    )
    scenario = Scenario.objects.create(project=project, slug="policy", name="Policy")
    bind_scenario_document_set(scenario=scenario, document_set=document_set, actor="seed")
    url = reverse("console:connector_schedule_configure", args=[source.pk])

    client.force_login(author)
    stage_payload = {
        f"schedule-{source.pk}-interval_seconds": "3600",
        f"schedule-{source.pk}-enabled": "on",
        f"schedule-{source.pk}-automation_mode": ScheduleAutomationMode.STAGE_ONLY,
        f"schedule-{source.pk}-embedding_profile": str(embedding.pk),
    }
    assert client.post(url, stage_payload).status_code == 302
    schedule = ConnectorSyncSchedule.objects.get(source=source)
    assert schedule.enabled is True
    assert schedule.automation_mode == ScheduleAutomationMode.STAGE_ONLY

    promote_payload = {
        **stage_payload,
        f"schedule-{source.pk}-automation_mode": ScheduleAutomationMode.PROMOTE_IF_SAFE,
        f"schedule-{source.pk}-scenarios": [str(scenario.pk)],
    }
    assert client.post(url, promote_payload).status_code == 403

    client.force_login(_member("release", org, Role.RELEASE_MANAGER))
    assert client.post(url, promote_payload).status_code == 302
    schedule.refresh_from_db()
    assert schedule.automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE
    assert list(schedule.promotion_targets.values_list("scenario_id", flat=True)) == [scenario.pk]


@pytest.mark.django_db
def test_foreign_source_run_is_not_found(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    foreign_set = create_document_set(
        organization=other, logical_id="foreign", name="Foreign", actor="seed"
    )
    foreign_author = _member("foreign", other, Role.SCENARIO_EDITOR)
    source = _rest_source(other, foreign_set, foreign_author)
    client.force_login(_member("author", org, Role.SCENARIO_EDITOR))
    assert client.post(reverse("console:connector_source_run", args=[source.pk])).status_code == 404
