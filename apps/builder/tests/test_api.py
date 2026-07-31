"""Operator builder API: authn, tenant/role authz, redaction, diagnostics, publish."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.builder.models import ArtifactDraft, WorkflowDraft
from apps.builder.tests.conftest import BuilderFixture, simple_workflow
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.orchestration.authoring import (
    AuthoringContract,
    AuthoringResponse,
    get_authoring_contract,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import OrganizationMembership
from apps.tools.models import ToolBinding, ToolDefinition, ToolRisk, ToolStatus
from apps.workflows.models import WorkflowVersion

pytestmark = pytest.mark.django_db


class FakeAuthoringProvider:
    response = AuthoringResponse(json.dumps(simple_workflow()), 12, 8)
    calls: list[dict] = []

    def generate(
        self,
        *,
        profile_id: str,
        description: str,
        contract: AuthoringContract,
        server_context: dict | None = None,
    ) -> AuthoringResponse:
        call: dict[str, Any] = {
            "profile_id": profile_id,
            "description": description,
            "artifact_type": contract.artifact_type,
            "contract_checksum": contract.checksum,
        }
        if server_context is not None:
            call["server_context"] = server_context
        self.calls.append(call)
        if contract.artifact_type in {"input_contract", "output_contract"}:
            return AuthoringResponse(
                json.dumps(
                    {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    }
                ),
                12,
                8,
            )
        return self.response

    def repair(
        self,
        *,
        profile_id: str,
        instruction: str,
        current_candidate: dict[str, Any],
        diagnostics: dict[str, Any],
        contract: AuthoringContract,
        server_context: dict[str, Any],
    ) -> AuthoringResponse:
        self.calls.append(
            {
                "operation": "repair",
                "profile_id": profile_id,
                "instruction": instruction,
                "current_candidate": current_candidate,
                "diagnostics": diagnostics,
                "artifact_type": contract.artifact_type,
                "server_context": server_context,
            }
        )
        return AuthoringResponse(
            json.dumps({"status": "workflow_candidate", "candidate": simple_workflow()}),
            15,
            9,
        )


def _post(client: Client, url: str, payload: dict):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def _put(client: Client, url: str, payload: dict):
    return client.put(url, data=json.dumps(payload), content_type="application/json")


# --- Authentication ---------------------------------------------------------


def test_unauthenticated_calls_return_401_json(client: Client, bf: BuilderFixture) -> None:
    scenario = Scenario.objects.create(project=bf.project, slug="auth", name="Auth")
    for url in [
        reverse("builder_api:drafts"),
        reverse("builder_api:artifact_drafts"),
        reverse("builder_api:draft_detail", args=[bf.draft.pk]),
        reverse("builder_api:node_schema") + "?organization=b-org",
        reverse("builder_api:release_manifest_preflight", args=[scenario.public_id]),
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


# --- Scenario Studio release manifest --------------------------------------


def _release_manager(bf: BuilderFixture) -> User:
    manager = User.objects.create_user("release-manager", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=bf.org, user=manager)
    for scenario in Scenario.objects.filter(project=bf.project):
        ScenarioResponsibilityAssignment.objects.create(
            organization=bf.org,
            membership=membership,
            scenario=scenario,
            responsibility=ScenarioResponsibility.RELEASE_MANAGER,
            assigned_by=manager,
        )
    return manager


def _release_scenario_and_workflow(bf: BuilderFixture) -> tuple[Scenario, ArtifactVersion]:
    scenario = Scenario.objects.create(
        project=bf.project,
        slug="release-studio",
        name="Release Studio",
    )
    workflow = create_artifact_version(
        organization=bf.org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="release_studio_flow",
        body=simple_workflow(),
        created_by="author",
    )
    return scenario, workflow


def test_release_manifest_preflight_is_exact_authorized_and_no_write(
    client: Client,
    bf: BuilderFixture,
) -> None:
    scenario, workflow = _release_scenario_and_workflow(bf)
    url = reverse("builder_api:release_manifest_preflight", args=[scenario.public_id])
    payload = {
        "items": [
            {
                "artifact_version_id": workflow.pk,
                "role": "workflow_definition",
            }
        ]
    }

    client.force_login(bf.author)
    assert _post(client, url, payload).status_code == 403

    client.force_login(_release_manager(bf))
    response = _post(client, url, payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["artifact_manifest_sha256"]
    assert not ScenarioRelease.objects.exists()
    assert not WorkflowVersion.objects.exists()
    assert not AuditEvent.objects.filter(action="console.scenario.release.compile").exists()

    requirements = _post(
        client,
        reverse("builder_api:release_manifest_requirements", args=[scenario.public_id]),
        {"workflow_artifact_id": workflow.pk},
    )
    assert requirements.status_code == 200
    assert requirements.json()["ok"] is True
    assert requirements.json()["requirements"] == [
        {
            "role": "workflow_definition",
            "artifact_type": "workflow_definition",
            "node_ids": [],
        }
    ]
    assert not ScenarioRelease.objects.exists()
    assert not WorkflowVersion.objects.exists()


def test_release_manifest_compile_preserves_safe_failure_and_audits_success(
    client: Client,
    bf: BuilderFixture,
) -> None:
    scenario, workflow = _release_scenario_and_workflow(bf)
    contract = create_artifact_version(
        organization=bf.org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="request_contract",
        body={"type": "object"},
        created_by="author",
    )
    url = reverse("builder_api:release_manifest_compile", args=[scenario.public_id])
    client.force_login(_release_manager(bf))

    rejected = _post(
        client,
        url,
        {
            "items": [
                {
                    "artifact_version_id": contract.pk,
                    "role": "input_contract",
                }
            ]
        },
    )

    assert rejected.status_code == 200
    assert rejected.json() == {
        "ok": False,
        "diagnostics": [
            {
                "code": "workflow_missing",
                "message": "Candidate manifest bir canonical workflow_definition pini içermelidir.",
                "role": "workflow_definition",
                "artifact_type": "workflow_definition",
            }
        ],
    }
    assert not ScenarioRelease.objects.exists()
    assert AuditEvent.objects.filter(
        action="console.scenario.release.compile",
        outcome="failure",
        reason="workflow_missing",
    ).exists()

    accepted = _post(
        client,
        url,
        {
            "items": [
                {
                    "artifact_version_id": workflow.pk,
                    "role": "workflow_definition",
                },
                {
                    "artifact_version_id": contract.pk,
                    "role": "input_contract",
                },
            ]
        },
    )

    assert accepted.status_code == 201
    assert accepted.json()["ok"] is True
    release = ScenarioRelease.objects.get()
    assert release.status == ReleaseStatus.CANDIDATE
    assert accepted.json()["release"]["id"] == release.pk
    assert AuditEvent.objects.filter(
        action="console.scenario.release.compile",
        outcome="success",
        resource_id=str(release.pk),
    ).exists()


def test_release_manifest_foreign_id_is_non_disclosing(
    client: Client,
    bf: BuilderFixture,
) -> None:
    scenario, _workflow = _release_scenario_and_workflow(bf)
    foreign = create_artifact_version(
        organization=bf.other_org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="foreign_private",
        logical_description="FOREIGN_LOGICAL_SECRET",
        version_description="FOREIGN_VERSION_SECRET",
        body={"type": "object"},
        created_by="foreign",
    )
    client.force_login(_release_manager(bf))

    response = _post(
        client,
        reverse("builder_api:release_manifest_preflight", args=[scenario.public_id]),
        {
            "items": [
                {
                    "artifact_version_id": foreign.pk,
                    "role": "input_contract",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["diagnostics"][0]["code"] == "artifact_not_found"
    rendered = response.content.decode()
    assert "FOREIGN_LOGICAL_SECRET" not in rendered
    assert "FOREIGN_VERSION_SECRET" not in rendered


def test_release_manifest_compile_rolls_back_when_audit_fails(
    client: Client,
    bf: BuilderFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, workflow = _release_scenario_and_workflow(bf)
    client.force_login(_release_manager(bf))

    def fail_audit(**_kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.builder.api.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _post(
            client,
            reverse("builder_api:release_manifest_compile", args=[scenario.public_id]),
            {
                "items": [
                    {
                        "artifact_version_id": workflow.pk,
                        "role": "workflow_definition",
                    }
                ]
            },
        )
    assert not ScenarioRelease.objects.exists()
    assert not WorkflowVersion.objects.exists()


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
        {
            "organization": "b-org",
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "name": "New flow",
            "logical_id": "flow_b",
            "body": {},
        },
    )
    assert response.status_code == 201
    assert WorkflowDraft.objects.filter(organization=bf.org, logical_id="flow_b").exists()
    assert AuditEvent.objects.filter(action="console.builder.draft.create").exists()


def test_author_creates_scenario_scoped_draft_and_rejects_foreign_scenario(
    client: Client, bf: BuilderFixture
) -> None:
    scenario = Scenario.objects.create(project=bf.project, slug="studio", name="Studio")
    ScenarioResponsibilityAssignment.objects.create(
        organization=bf.org,
        membership=OrganizationMembership.objects.get(organization=bf.org, user=bf.author),
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=bf.author,
    )
    foreign_project = AIProject.objects.create(
        organization=bf.other_org, slug="foreign", name="Foreign"
    )
    foreign = Scenario.objects.create(project=foreign_project, slug="private", name="Private")
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:drafts"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": scenario.pk,
            "name": "Studio flow",
            "logical_id": "studio_flow",
            "body": {},
        },
    )
    assert response.status_code == 201
    assert response.json()["scenario_id"] == scenario.pk
    denied = _post(
        client,
        reverse("builder_api:drafts"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": foreign.pk,
            "name": "Forged",
            "logical_id": "forged",
            "body": {},
        },
    )
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "scenario_not_found"
    assert not WorkflowDraft.objects.filter(logical_id="forged").exists()


def test_non_author_cannot_create(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.viewer)
    response = _post(
        client,
        reverse("builder_api:drafts"),
        {
            "organization": "b-org",
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "name": "x",
            "logical_id": "flow_c",
            "body": {},
        },
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
        {
            "organization": "b-org",
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "name": "dup",
            "logical_id": "flow_a",
            "body": {},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_logical_id"


# --- Update / delete --------------------------------------------------------


def test_author_updates_draft_body(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    response = _put(client, url, {"revision": 1, "name": "Renamed", "body": {"kind": "Workflow"}})
    assert response.status_code == 200
    bf.draft.refresh_from_db()
    assert bf.draft.name == "Renamed"
    assert bf.draft.updated_by == "author"
    assert bf.draft.revision == 2


def test_stale_workflow_update_is_conflict_without_mutation(
    client: Client, bf: BuilderFixture
) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    assert _put(client, url, {"revision": 1, "name": "First editor"}).status_code == 200
    response = _put(
        client,
        url,
        {"revision": 1, "name": "STALE_PRIVATE_BODY", "body": {"secret": "PRIVATE"}},
    )
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "stale_revision", "message": "stale_revision"}}
    bf.draft.refresh_from_db()
    assert bf.draft.name == "First editor"
    assert bf.draft.body == simple_workflow()


def test_non_author_cannot_update_or_delete(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.viewer)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    assert _put(client, url, {"name": "nope"}).status_code == 403
    assert client.delete(url).status_code == 403
    assert WorkflowDraft.objects.filter(pk=bf.draft.pk).exists()


def test_author_deletes_draft(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    url = reverse("builder_api:draft_detail", args=[bf.draft.pk])
    assert (
        client.delete(
            url, data=json.dumps({"revision": 1}), content_type="application/json"
        ).status_code
        == 200
    )
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
    response = _post(
        client,
        url,
        {"revision": 1, "version_description": "Initial reviewed workflow"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["artifact_type"] == "workflow_definition"
    assert data["version"] == 1
    artifact = ArtifactVersion.objects.get(
        organization=bf.org, type="workflow_definition", logical_id="flow_a"
    )
    assert artifact.checksum == data["checksum"]
    assert artifact.logical_description == "Stable flow purpose"
    assert artifact.version_description == "Initial reviewed workflow"
    assert AuditEvent.objects.filter(action="console.builder.draft.publish").exists()
    bf.draft.refresh_from_db()
    assert bf.draft.last_published_version == 1
    assert bf.draft.revision == 2


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
    response = _post(client, url, {"revision": 1})
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
    schemas = {node["type"]: node["fields"] for node in data["node_types"]}
    assert [field["name"] for field in schemas["generate"]] == [
        "prompt_ref",
        "model_profile_ref",
    ]
    assert all(field["required"] is False for field in schemas["generate"])
    assert [field["name"] for field in schemas["format_output"]] == ["template_ref"]
    assert schemas["input"] == []
    assert schemas["retrieve"] == []
    assert schemas["validate_contract"] == []
    assert schemas["end"] == []
    # The tool endpoint and secret reference must never reach the client.
    assert "secret.internal" not in raw
    assert "secret:search-token" not in raw
    assert "endpoint" not in raw


def test_node_schema_includes_transform_and_mapping_metadata(
    client: Client, bf: BuilderFixture
) -> None:
    client.force_login(bf.author)
    data = client.get(reverse("builder_api:node_schema") + "?organization=b-org").json()
    by_type = {node["type"]: node for node in data["node_types"]}
    # The transform node is exposed with its pinned-profile reference field.
    assert "transform" in by_type
    assert [field["name"] for field in by_type["transform"]["fields"]] == ["transform_profile_ref"]
    # Mapping-eligible nodes advertise the capability; control/IO nodes do not.
    assert by_type["transform"]["supports_mapping"] is True
    assert by_type["tool"]["supports_mapping"] is True
    assert "supports_mapping" not in by_type["condition"]
    # The mapping metadata mirrors the backend contract (non-authoritative UI hint).
    assert data["mapping"]["entry_keys"] == ["from", "to"]
    assert set(data["mapping"]["writable_roots"]) == {
        "input",
        "retrieval",
        "branches",
        "evidence",
        "decisions",
        "output",
    }


def test_node_schema_exposes_all_verified_node_families(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    data = client.get(reverse("builder_api:node_schema") + "?organization=b-org").json()
    by_type = {node["type"]: node for node in data["node_types"]}
    # Every verified runtime builtin family is authorable in Studio (P2.6.11).
    assert {
        "parallel",
        "for_each",
        "join",
        "subworkflow",
    } <= set(by_type)
    # Branch-region owners are flagged so the client can render their region/edges.
    assert by_type["parallel"]["branch_owner"] is True
    assert by_type["for_each"]["branch_owner"] is True
    # Join advertises its policy modes as a closed enum.
    mode_field = next(f for f in by_type["join"]["fields"] if f["name"] == "mode")
    assert mode_field["options"] == ["all", "threshold", "fail_fast"]
    assert by_type["subworkflow"]["composition"] is True
    assert by_type["subworkflow"]["mapping_required"] is True
    # Retry/compensation affordances are surfaced as UI hints.
    assert by_type["transform"]["supports_retry"] is True
    assert by_type["tool"]["supports_compensation"] is True
    assert "supports_retry" not in by_type["condition"]
    assert data["retry_policy"]["retry_on"] == ["transient"]
    assert data["gates"]["composition_enabled"] is True
    assert data["gates"]["agent_loop_enabled"] is True
    assert by_type["agent_loop"]["agent_loop"] is True
    assert by_type["agent_loop"]["mapping_required"] is True


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
    response = _post(
        csrf_client,
        reverse("builder_api:ai_candidate_repair"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": 1,
            "candidate": {},
        },
    )
    assert response.status_code == 403
    assert not WorkflowDraft.objects.filter(logical_id="flow_csrf").exists()
    response = _post(
        csrf_client,
        reverse("builder_api:ai_candidates"),
        {"organization": bf.org.slug, "description": "workflow"},
    )
    assert response.status_code == 403
    artifact_draft = ArtifactDraft.objects.create(
        organization=bf.org,
        project=bf.project,
        artifact_type="input_contract",
        name="Girdi",
        logical_id="csrf_input",
        body={"type": "object"},
        created_by="author",
        updated_by="author",
    )
    response = _put(
        csrf_client,
        reverse("builder_api:artifact_draft_detail", args=[artifact_draft.pk]),
        {"name": "CSRF bypass"},
    )
    assert response.status_code == 403
    artifact_draft.refresh_from_db()
    assert artifact_draft.name == "Girdi"


# --- AI-assisted candidates -------------------------------------------------


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
def test_ai_repair_is_transient_scoped_and_audited_without_content(
    client: Client, bf: BuilderFixture
) -> None:
    cache.clear()
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="repair-loop",
        name="Repair Loop",
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=bf.org,
        membership=OrganizationMembership.objects.get(organization=bf.org, user=bf.author),
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=bf.author,
    )
    invalid_candidate = {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "broken"},
        "spec": {"input_node": "missing", "nodes": [], "edges": []},
    }
    instruction = "Eksik baÅŸlangÄ±Ã§ ve bitiÅŸ node'larÄ±nÄ± ekle."
    before_drafts = WorkflowDraft.objects.count()
    FakeAuthoringProvider.calls.clear()
    client.force_login(bf.author)

    response = _post(
        client,
        reverse("builder_api:ai_candidate_repair"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": scenario.pk,
            "candidate": invalid_candidate,
            "instruction": instruction,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "workflow_candidate"
    assert response.json()["diagnostics"]["ok"] is True
    assert response.json()["repair"]["before_diagnostic_codes"]
    assert response.json()["repair"]["after_diagnostic_codes"] == []
    call = FakeAuthoringProvider.calls[0]
    assert call["operation"] == "repair"
    assert call["instruction"] == instruction
    assert call["current_candidate"] == invalid_candidate
    assert call["diagnostics"]["ok"] is False
    assert call["server_context"]["scenario"]["slug"] == "repair-loop"
    assert WorkflowDraft.objects.count() == before_drafts
    assert not ArtifactVersion.objects.exists()
    assert not ScenarioRelease.objects.exists()
    audit_json = json.dumps(
        list(AuditEvent.objects.filter(action="console.builder.ai_candidate.repair").values()),
        default=str,
    )
    assert instruction not in audit_json
    assert "missing" not in audit_json


def test_ai_repair_requires_author_and_exact_scenario(client: Client, bf: BuilderFixture) -> None:
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="repair-scope",
        name="Repair Scope",
    )
    payload = {
        "organization": bf.org.slug,
        "project_id": bf.project.pk,
        "scenario_id": scenario.pk,
        "candidate": simple_workflow(),
    }
    client.force_login(bf.viewer)
    assert _post(client, reverse("builder_api:ai_candidate_repair"), payload).status_code == 403

    client.force_login(bf.author)
    payload["scenario_id"] = 987654321
    response = _post(client, reverse("builder_api:ai_candidate_repair"), payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "scenario_not_found"


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
def test_ai_candidate_is_transient_then_explicitly_accepted(
    client: Client, bf: BuilderFixture
) -> None:
    cache.clear()
    FakeAuthoringProvider.calls.clear()
    FakeAuthoringProvider.response = AuthoringResponse(
        json.dumps({"status": "workflow_candidate", "candidate": simple_workflow()}),
        12,
        8,
    )
    client.force_login(bf.author)
    generated = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "description": "Bir giriş ve bitiş akışı oluştur.",
        },
    )
    assert generated.status_code == 200
    assert generated.json()["diagnostics"]["ok"] is True
    assert FakeAuthoringProvider.calls[0]["profile_id"].startswith("1111")
    assert WorkflowDraft.objects.count() == 1
    assert not ArtifactVersion.objects.exists()


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
def test_studio_ai_uses_scoped_context_and_server_identifier(
    client: Client, bf: BuilderFixture
) -> None:
    cache.clear()
    scenario = Scenario.objects.create(
        organization=bf.org,
        project=bf.project,
        slug="planner",
        name="Planner",
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=bf.org,
        membership=OrganizationMembership.objects.get(organization=bf.org, user=bf.author),
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=bf.author,
    )
    FakeAuthoringProvider.calls.clear()
    FakeAuthoringProvider.response = AuthoringResponse(
        json.dumps({"status": "workflow_candidate", "candidate": simple_workflow()})
    )
    client.force_login(bf.author)
    before = WorkflowDraft.objects.count()
    generated = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": scenario.pk,
            "description": "Akış oluştur",
        },
    )
    assert generated.status_code == 200
    assert generated.json()["status"] == "workflow_candidate"
    assert WorkflowDraft.objects.count() == before
    assert FakeAuthoringProvider.calls[0]["server_context"]["scenario"]["slug"] == "planner"

    accepted = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": scenario.pk,
            "name": "Planner akışı",
            "candidate": generated.json()["candidate"],
            "prompt_contract": generated.json()["prompt_contract"],
            "authoring_context": generated.json()["authoring_context"],
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["logical_id"].startswith("planner-akisi-")
    assert accepted.json()["scenario_id"] == scenario.pk
    FakeAuthoringProvider.response = AuthoringResponse(json.dumps(simple_workflow()), 12, 8)

    accepted = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "name": "AI flow",
            "logical_id": "ai_flow",
            "candidate": generated.json()["candidate"],
        },
    )
    assert accepted.status_code == 400
    assert accepted.json()["error"]["code"] == "authoring_context_required"
    assert not WorkflowDraft.objects.filter(logical_id="ai_flow", project=bf.project).exists()
    assert not ArtifactVersion.objects.exists()


def test_ai_candidate_disabled_and_role_denials(client: Client, bf: BuilderFixture) -> None:
    cache.clear()
    url = reverse("builder_api:ai_candidates")
    client.force_login(bf.author)
    assert (
        _post(
            client,
            url,
            {
                "organization": bf.org.slug,
                "project_id": bf.project.pk,
                "scenario_id": bf.scenario.pk,
                "description": "x",
            },
        ).json()["error"]["code"]
        == "ai_authoring_disabled"
    )
    client.force_login(bf.viewer)
    assert (
        _post(
            client,
            url,
            {
                "organization": bf.org.slug,
                "project_id": bf.project.pk,
                "scenario_id": bf.scenario.pk,
                "description": "x",
            },
        ).status_code
        == 403
    )
    client.force_login(bf.outsider)
    assert (
        _post(
            client,
            url,
            {
                "organization": bf.org.slug,
                "project_id": bf.project.pk,
                "scenario_id": bf.scenario.pk,
                "description": "x",
            },
        ).status_code
        == 404
    )


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
    AI_AUTHORING_RATE_LIMIT=1,
)
def test_ai_candidate_rate_limit_and_audit_redaction(client: Client, bf: BuilderFixture) -> None:
    cache.clear()
    FakeAuthoringProvider.response = AuthoringResponse(
        json.dumps({"status": "workflow_candidate", "candidate": simple_workflow()}),
        12,
        8,
    )
    client.force_login(bf.author)
    secret_text = "özel-içerik-123"  # noqa: S105 -- redaction sentinel, not a credential
    url = reverse("builder_api:ai_candidates")
    assert (
        _post(
            client,
            url,
            {
                "organization": bf.org.slug,
                "project_id": bf.project.pk,
                "scenario_id": bf.scenario.pk,
                "description": secret_text,
            },
        ).status_code
        == 200
    )
    limited = _post(
        client,
        url,
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "description": secret_text,
        },
    )
    assert limited.status_code == 400
    assert limited.json()["error"]["code"] == "rate_limited"
    assert secret_text not in json.dumps(list(AuditEvent.objects.values()), default=str)


def test_ai_accept_revalidates_and_never_publishes(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "name": "bad",
            "logical_id": "bad",
            "candidate": {"kind": "Workflow"},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "candidate_invalid_workflow"
    assert not WorkflowDraft.objects.filter(logical_id="bad").exists()
    assert not ArtifactVersion.objects.exists()


def test_ai_accept_rejects_foreign_project(client: Client, bf: BuilderFixture) -> None:
    foreign_project = type(bf.project).objects.create(
        organization=bf.other_org, slug="foreign", name="Foreign"
    )
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            "organization": bf.org.slug,
            "project_id": foreign_project.pk,
            "name": "x",
            "logical_id": "foreign",
            "candidate": simple_workflow(),
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "project_not_found"
    assert not WorkflowDraft.objects.filter(logical_id="foreign").exists()


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
    AI_AUTHORING_MAX_DESCRIPTION_BYTES=8,
    AI_AUTHORING_MAX_CANDIDATE_BYTES=32,
)
def test_ai_request_body_limits_apply_before_json_decoding(
    client: Client, bf: BuilderFixture
) -> None:
    cache.clear()
    client.force_login(bf.author)
    generated = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {"organization": bf.org.slug, "description": "x" * 20_000},
    )
    assert generated.status_code == 400
    assert generated.json()["error"]["code"] == "request_too_large"
    accepted = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "name": "x",
            "logical_id": "large",
            "candidate": {"padding": "x" * 20_000},
        },
    )
    assert accepted.status_code == 400
    assert accepted.json()["error"]["code"] == "request_too_large"
    assert not WorkflowDraft.objects.filter(logical_id="large").exists()


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
def test_ai_candidate_rejects_caller_destination_and_profile_fields(
    client: Client, bf: BuilderFixture
) -> None:
    cache.clear()
    FakeAuthoringProvider.calls.clear()
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "description": "workflow",
            "profile_id": "attacker",
            "endpoint": "https://attacker.invalid/",
            "headers": {"Authorization": "attacker"},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unexpected_field"
    assert FakeAuthoringProvider.calls == []


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
def test_ai_candidate_requires_exact_project(client: Client, bf: BuilderFixture) -> None:
    cache.clear()
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {"organization": bf.org.slug, "description": "workflow"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "project_required"


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
@pytest.mark.parametrize("artifact_type", ["input_contract", "output_contract"])
def test_ai_contract_candidate_transfers_to_non_publishing_artifact_draft(
    client: Client, bf: BuilderFixture, artifact_type: str
) -> None:
    cache.clear()
    FakeAuthoringProvider.calls.clear()
    client.force_login(bf.author)
    generated = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "artifact_type": artifact_type,
            "description": "Metin sorgusu alan bir JSON sözleşmesi oluştur.",
        },
    )
    assert generated.status_code == 200
    result = generated.json()
    assert result["artifact_type"] == artifact_type
    assert result["diagnostics"]["ok"] is True
    assert len(result["prompt_contract"]["checksum"]) == 64
    assert len(FakeAuthoringProvider.calls) == 1
    provider_call = FakeAuthoringProvider.calls[0]
    assert provider_call["profile_id"] == "11111111-1111-1111-1111-111111111111"
    assert provider_call["artifact_type"] == artifact_type
    assert provider_call["contract_checksum"] == result["prompt_contract"]["checksum"]
    assert provider_call["server_context"]["scenario"]["slug"] == bf.scenario.slug
    assert not ArtifactDraft.objects.exists()

    accepted = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "artifact_type": artifact_type,
            "prompt_contract": result["prompt_contract"],
            "name": "AI sözleşmesi",
            "logical_id": f"ai_{artifact_type}",
            "candidate": result["candidate"],
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["draft_kind"] == "artifact"
    assert ArtifactDraft.objects.filter(
        organization=bf.org,
        project=bf.project,
        artifact_type=artifact_type,
        logical_id=f"ai_{artifact_type}",
    ).exists()
    assert not ArtifactVersion.objects.exists()
    audit = AuditEvent.objects.get(action="console.builder.artifact_draft.create")
    assert audit.after == {"prompt_contract": result["prompt_contract"]}


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
)
@pytest.mark.parametrize(
    "artifact_type",
    [
        "custom_node_definition",
        "model_profile",
        "source_definition",
        "tool_binding",
        "tool_definition",
        "unknown",
    ],
)
def test_ai_candidate_rejects_high_risk_or_unknown_type_before_egress(
    client: Client, bf: BuilderFixture, artifact_type: str
) -> None:
    cache.clear()
    FakeAuthoringProvider.calls.clear()
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "artifact_type": artifact_type,
            "description": "x",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_artifact_type"
    assert FakeAuthoringProvider.calls == []


def test_ai_contract_accept_revalidates_schema_and_contract_metadata(
    client: Client, bf: BuilderFixture
) -> None:
    client.force_login(bf.author)
    contract = get_authoring_contract("input_contract")
    base = {
        "organization": bf.org.slug,
        "project_id": bf.project.pk,
        "scenario_id": bf.scenario.pk,
        "artifact_type": "input_contract",
        "name": "bad",
        "logical_id": "bad_contract",
        "candidate": {"type": 42},
        "prompt_contract": {
            "id": contract.contract_id,
            "revision": contract.revision,
            "checksum": contract.checksum,
        },
    }
    invalid = _post(client, reverse("builder_api:ai_candidate_accept"), base)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "candidate_invalid_artifact"

    missing_metadata = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {key: value for key, value in base.items() if key != "prompt_contract"},
    )
    assert missing_metadata.status_code == 400
    assert missing_metadata.json()["error"]["code"] == "prompt_contract_required"

    mismatch = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            **base,
            "candidate": {"type": "object"},
            "prompt_contract": {"id": "attacker", "revision": 1, "checksum": "0" * 64},
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "prompt_contract_mismatch"
    inline_secret = _post(
        client,
        reverse("builder_api:ai_candidate_accept"),
        {
            **base,
            "logical_id": "secret_contract",
            "candidate": {"type": "object", "api_key": "literal-secret-value"},
        },
    )
    assert inline_secret.status_code == 400
    assert inline_secret.json()["error"]["code"] == "candidate_invalid_artifact"
    assert not ArtifactDraft.objects.exists()
    assert not ArtifactVersion.objects.exists()


@override_settings(
    AI_AUTHORING_MODEL_PROFILE_ID="11111111-1111-1111-1111-111111111111",
    AI_AUTHORING_PROVIDER="apps.builder.tests.test_api.FakeAuthoringProvider",
    AI_AUTHORING_CONTRACT_REVISION=999,
)
def test_ai_candidate_rejects_unavailable_contract_revision_before_egress(
    client: Client, bf: BuilderFixture
) -> None:
    FakeAuthoringProvider.calls.clear()
    client.force_login(bf.author)
    response = _post(
        client,
        reverse("builder_api:ai_candidates"),
        {
            "organization": bf.org.slug,
            "project_id": bf.project.pk,
            "scenario_id": bf.scenario.pk,
            "artifact_type": "input_contract",
            "description": "x",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "authoring_contract_unavailable"
    assert FakeAuthoringProvider.calls == []


def test_artifact_draft_is_tenant_scoped_mutable_and_has_no_publish_action(
    client: Client, bf: BuilderFixture
) -> None:
    draft = ArtifactDraft.objects.create(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type="input_contract",
        name="Girdi",
        logical_id="input_v1",
        body={"type": "object"},
        created_by="author",
        updated_by="author",
    )
    detail_url = reverse("builder_api:artifact_draft_detail", args=[draft.pk])
    diagnostics_url = reverse("builder_api:artifact_draft_diagnostics", args=[draft.pk])

    client.force_login(bf.viewer)
    assert client.get(detail_url).json()["can_write"] is False
    assert _put(client, detail_url, {"name": "No"}).status_code == 403

    client.force_login(bf.outsider)
    assert client.get(detail_url).status_code == 404
    assert _post(client, diagnostics_url, {}).status_code == 404

    client.force_login(bf.author)
    listed = client.get(reverse("builder_api:artifact_drafts")).json()["drafts"]
    assert [item["logical_id"] for item in listed] == ["input_v1"]
    diagnostics = _post(client, diagnostics_url, {"body": {"type": 42}})
    assert diagnostics.status_code == 200
    assert diagnostics.json()["ok"] is False
    updated = _put(
        client,
        detail_url,
        {"revision": 1, "name": "Girdi v2", "body": {"type": "object", "properties": {}}},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Girdi v2"
    # POST is deliberately absent: generic drafts cannot publish in P10.2.
    assert _post(client, detail_url, {}).status_code == 405
    assert not ArtifactVersion.objects.exists()
    assert (
        client.delete(
            detail_url, data=json.dumps({"revision": 2}), content_type="application/json"
        ).status_code
        == 200
    )
    assert not ArtifactDraft.objects.exists()
    assert AuditEvent.objects.filter(action="console.builder.artifact_draft.update").exists()
    assert AuditEvent.objects.filter(action="console.builder.artifact_draft.delete").exists()


def test_artifact_draft_update_revalidates_and_rejects_unknown_fields(
    client: Client, bf: BuilderFixture
) -> None:
    draft = ArtifactDraft.objects.create(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type="output_contract",
        name="Çıktı",
        logical_id="output_v1",
        body={"type": "object"},
        created_by="author",
        updated_by="author",
    )
    client.force_login(bf.author)
    url = reverse("builder_api:artifact_draft_detail", args=[draft.pk])
    invalid = _put(client, url, {"revision": 1, "body": {"type": 42}})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "candidate_invalid_artifact"
    unexpected = _put(client, url, {"artifact_type": "input_contract"})
    assert unexpected.status_code == 400
    assert unexpected.json()["error"]["code"] == "unexpected_field"
    draft.refresh_from_db()
    assert draft.artifact_type == "output_contract"


def test_stale_artifact_draft_update_is_conflict_without_mutation(
    client: Client, bf: BuilderFixture
) -> None:
    draft = ArtifactDraft.objects.create(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type="input_contract",
        name="Original",
        logical_id="concurrent_input",
        body={"type": "object"},
        created_by="author",
        updated_by="author",
    )
    client.force_login(bf.author)
    url = reverse("builder_api:artifact_draft_detail", args=[draft.pk])
    assert _put(client, url, {"revision": 1, "name": "First editor"}).status_code == 200
    response = _put(
        client,
        url,
        {"revision": 1, "name": "STALE_PRIVATE", "body": {"type": "string"}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_revision"
    draft.refresh_from_db()
    assert draft.name == "First editor"
    assert draft.body == {"type": "object"}
