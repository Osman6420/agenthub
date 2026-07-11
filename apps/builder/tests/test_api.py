"""Operator builder API: authn, tenant/role authz, redaction, diagnostics, publish."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.audit.models import AuditEvent
from apps.builder.models import WorkflowDraft
from apps.builder.tests.conftest import BuilderFixture, simple_workflow
from apps.tools.models import ToolBinding, ToolDefinition, ToolRisk, ToolStatus

pytestmark = pytest.mark.django_db


def _post(client: Client, url: str, payload: dict):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def _put(client: Client, url: str, payload: dict):
    return client.put(url, data=json.dumps(payload), content_type="application/json")


# --- Authentication ---------------------------------------------------------


def test_unauthenticated_calls_return_401_json(client: Client, bf: BuilderFixture) -> None:
    for url in [
        reverse("builder_api:drafts"),
        reverse("builder_api:draft_detail", args=[bf.draft.pk]),
        reverse("builder_api:node_schema") + "?organization=b-org",
    ]:
        response = client.get(url)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"


# --- Tenant scoping & read --------------------------------------------------


def test_draft_list_is_tenant_scoped(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    body = client.get(reverse("builder_api:drafts")).json()
    ids = [d["logical_id"] for d in body["drafts"]]
    assert ids == ["flow_a"]

    client.force_login(bf.outsider)
    assert client.get(reverse("builder_api:drafts")).json()["drafts"] == []


def test_cross_tenant_draft_is_not_found(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.outsider)
    response = client.get(reverse("builder_api:draft_detail", args=[bf.draft.pk]))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_retrieve_reports_can_write_by_role(client: Client, bf: BuilderFixture) -> None:
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])

    client.force_login(bf.author)
    assert client.get(url).json()["can_write"] is True

    # An auditor has read scope but cannot author -> read-only mode in the SPA.
    client.force_login(bf.viewer)
    assert client.get(url).json()["can_write"] is False


# --- Create -----------------------------------------------------------------


def test_author_creates_draft(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:drafts"),
        {"organization": "b-org", "name": "New flow", "logical_id": "flow_b", "body": {}},
    )
    assert response.status_code == 201
    assert WorkflowDraft.objects.filter(organization=bf.org, logical_id="flow_b").exists()
    assert AuditEvent.objects.filter(action="console.builder.draft.create").exists()


def test_non_author_cannot_create(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.viewer)
    response = _post(
        client,
        reverse("builder_api:drafts"),
        {"organization": "b-org", "name": "x", "logical_id": "flow_c", "body": {}},
    )
    assert response.status_code == 403
    assert not WorkflowDraft.objects.filter(logical_id="flow_c").exists()


def test_create_in_out_of_scope_org_is_not_found(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.outsider)
    response = _post(
        client,
        reverse("builder_api:drafts"),
        {"organization": "b-org", "name": "x", "logical_id": "flow_d", "body": {}},
    )
    assert response.status_code == 404
    assert not WorkflowDraft.objects.filter(logical_id="flow_d").exists()


def test_duplicate_logical_id_is_rejected(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:drafts"),
        {"organization": "b-org", "name": "dup", "logical_id": "flow_a", "body": {}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_logical_id"


# --- Update / delete --------------------------------------------------------


def test_author_updates_draft_body(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    response = _put(client, url, {"name": "Renamed", "body": {"kind": "Workflow"}})
    assert response.status_code == 200
    bf.draft.refresh_from_db()
    assert bf.draft.name == "Renamed"
    assert bf.draft.updated_by == "author"


def test_non_author_cannot_update_or_delete(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.viewer)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    assert _put(client, url, {"name": "nope"}).status_code == 403
    assert client.delete(url).status_code == 403
    assert WorkflowDraft.objects.filter(pk=bf.draft.pk).exists()


def test_author_deletes_draft(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    assert client.delete(url).status_code == 200
    assert not WorkflowDraft.objects.filter(pk=bf.draft.pk).exists()


# --- Diagnostics ------------------------------------------------------------


def test_diagnostics_valid_body(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_diagnostics", args=[bf.draft.pk])
    body = _post(client, url, {"body": simple_workflow()}).json()
    assert body["ok"] is True
    assert body["compiled_checksum"]
    # Diagnostics never persist an artifact.
    assert not ArtifactVersion.objects.filter(organization=bf.org).exists()


def test_diagnostics_invalid_body_returns_errors(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_diagnostics", args=[bf.draft.pk])
    broken = {"api_version": "agenthub/v1", "kind": "Workflow", "metadata": {"id": "x"}}
    body = _post(client, url, {"body": broken}).json()
    assert body["ok"] is False
    assert body["errors"]


# --- Publish ----------------------------------------------------------------


def test_publish_creates_workflow_artifact(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_publish", args=[bf.draft.pk])
    response = _post(client, url, {})
    assert response.status_code == 201
    data = response.json()
    assert data["artifact_type"] == "workflow_definition"
    assert data["version"] == 1
    artifact = ArtifactVersion.objects.get(
        organization=bf.org, type="workflow_definition", logical_id="flow_a"
    )
    assert artifact.checksum == data["checksum"]
    assert AuditEvent.objects.filter(action="console.builder.draft.publish").exists()
    bf.draft.refresh_from_db()
    assert bf.draft.last_published_version == 1


def test_non_author_cannot_publish(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.viewer)
    url = reverse("builder_api:draft_publish", args=[bf.draft.pk])
    assert _post(client, url, {}).status_code == 403
    assert not ArtifactVersion.objects.filter(organization=bf.org).exists()


def test_publish_rejects_inline_secret(client: Client, bf: BuilderFixture) -> None:
    # A DSL that compiles but carries a literal secret must be rejected by the shared
    # validator — the builder grants no bypass.
    body = simple_workflow()
    body["spec"]["nodes"][1]["config"]["token"] = "AKIAEXAMPLELITERAL"  # noqa: S105
    bf.draft.body = body
    bf.draft.save(update_fields=["body"])

    client.force_login(bf.author)
    url = reverse("builder_api:draft_publish", args=[bf.draft.pk])
    response = _post(client, url, {})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "publish_rejected"
    assert not ArtifactVersion.objects.filter(organization=bf.org).exists()


# --- Node schema (redaction) ------------------------------------------------


def test_node_schema_exposes_roles_never_endpoints_or_secrets(
    client: Client, bf: BuilderFixture
) -> None:
    definition = ToolDefinition.objects.create(
        organization=bf.org,
        logical_id="search_def",
        version=1,
        manifest={"endpoint": "https://tools.secret.internal/search"},
        checksum="d" * 64,
        protocol="http",
        risk=ToolRisk.LOW,
        side_effecting=False,
        status=ToolStatus.ACTIVE,
    )
    ToolBinding.objects.create(
        organization=bf.org,
        tool_definition=definition,
        logical_id="search_web",
        version=1,
        manifest={"credentials": "secret:search-token"},
        checksum="e" * 64,
        approval_required=True,
        status=ToolStatus.ACTIVE,
    )

    client.force_login(bf.author)
    response = client.get(reverse("builder_api:node_schema") + "?organization=b-org")
    assert response.status_code == 200
    raw = response.content.decode()
    data = response.json()

    roles = {r["role"]: r["approval_required"] for r in data["tool_binding_roles"]}
    assert roles == {"search_web": True}
    node_types = {n["type"] for n in data["node_types"]}
    assert {"input", "tool", "condition", "custom", "end"} <= node_types
    # The tool endpoint and secret reference must never reach the client.
    assert "secret.internal" not in raw
    assert "secret:search-token" not in raw
    assert "endpoint" not in raw


def test_node_schema_excludes_other_tenant_bindings(client: Client, bf: BuilderFixture) -> None:
    other_def = ToolDefinition.objects.create(
        organization=bf.other_org,
        logical_id="foreign_def",
        version=1,
        manifest={"endpoint": "https://x/"},
        checksum="a" * 64,
        protocol="http",
        risk=ToolRisk.LOW,
        side_effecting=False,
        status=ToolStatus.ACTIVE,
    )
    ToolBinding.objects.create(
        organization=bf.other_org,
        tool_definition=other_def,
        logical_id="foreign_role",
        version=1,
        manifest={},
        checksum="b" * 64,
        approval_required=False,
        status=ToolStatus.ACTIVE,
    )
    client.force_login(bf.author)
    data = client.get(reverse("builder_api:node_schema") + "?organization=b-org").json()
    assert data["tool_binding_roles"] == []


# --- CSRF -------------------------------------------------------------------


def test_mutations_require_csrf_token(bf: BuilderFixture) -> None:
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(bf.author)
    response = _post(
        csrf_client,
        reverse("builder_api:drafts"),
        {"organization": "b-org", "name": "x", "logical_id": "flow_csrf", "body": {}},
    )
    assert response.status_code == 403
    assert not WorkflowDraft.objects.filter(logical_id="flow_csrf").exists()
