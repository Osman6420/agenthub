"""Seed a complete local demo tenant so every feature can be exercised by hand.

Local development / manual-testing convenience ONLY — never for production. It creates
operator accounts (one per role), a demo organization/project, one scenario of each
workload type (RAG, workflow-with-approval, agent), their immutable artifacts + promoted
releases, and a consumer with a bearer token bound to all three. It is idempotent per
entity (safe to re-run) and prints the credentials/token it minted.

Passwords/tokens are generated at run time and printed once; nothing sensitive is stored
in source. Run::

    python manage.py seed_demo            # prints a generated operator password
    python manage.py seed_demo --password <your-dev-password>
"""

from __future__ import annotations

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias, ScenarioType
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.roles import Role
from apps.identity.tokens import create_token
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tools.services import register_tool_binding, register_tool_definition

User = get_user_model()

ORG_SLUG = "demo"
CONSUMER_SUBJECT = "demo-client"

# Operator accounts: one per role so tenant-scoping and role gating can be exercised.
OPERATORS = [
    ("admin", Role.ORGANIZATION_ADMIN, True),  # also a superuser (platform admin)
    ("editor", Role.SCENARIO_EDITOR, False),
    ("releaser", Role.RELEASE_MANAGER, False),
    ("approver", Role.APPROVER, False),
    ("auditor", Role.AUDITOR, False),
]


class Command(BaseCommand):
    help = "Seed a local demo tenant (operators, scenarios, releases, consumer token)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--password",
            default="",
            help="Password for all seeded operator accounts (generated if omitted).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the existing demo organization (and all its data) first.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        password = options["password"] or secrets.token_urlsafe(9)

        with transaction.atomic():
            if options["reset"]:
                self._reset()
            org, _ = Organization.objects.get_or_create(
                slug=ORG_SLUG, defaults={"name": "Demo Org"}
            )
            self._ensure_operators(org, password)
            project, _ = AIProject.objects.get_or_create(
                organization=org, slug="support", defaults={"name": "Support"}
            )
            self._ensure_rag(org, project)
            self._ensure_workflow(org, project)
            self._ensure_agent(org, project)
            consumer = self._ensure_consumer(org)
            _, raw_token = create_token(consumer, f"demo-cli-{secrets.token_hex(3)}")

        self._report(password, raw_token)

    # --- reset --------------------------------------------------------------

    def _reset(self) -> None:
        """Delete the demo org's data leaf-first (many FKs are PROTECT by design)."""
        org = Organization.objects.filter(slug=ORG_SLUG).first()
        if org is None:
            return
        from apps.agents.models import AgentRun, AgentVersion
        from apps.artifacts.models import ArtifactVersion
        from apps.builder.models import WorkflowDraft
        from apps.evaluations.models import EvalRun
        from apps.releases.models import ReleaseCanary, ScenarioRelease
        from apps.tools.models import ApprovalRequest, ToolBinding, ToolDefinition, ToolInvocation
        from apps.workflows.models import WorkflowRun, WorkflowVersion

        by_org = {"organization": org}
        by_scope = {"scenario__project__organization": org}
        # Runs/invocations/approvals protect scenarios and releases — delete them first.
        ApprovalRequest.objects.filter(**by_org).delete()
        ToolInvocation.objects.filter(**by_org).delete()
        WorkflowRun.objects.filter(**by_org).delete()
        AgentRun.objects.filter(**by_org).delete()
        ReleaseCanary.objects.filter(**by_scope).delete()
        EvalRun.objects.filter(**by_org).delete()
        # Compiled versions protect their source artifacts; releases protect scenarios.
        WorkflowVersion.objects.filter(**by_org).delete()
        AgentVersion.objects.filter(**by_org).delete()
        ScenarioRelease.objects.filter(**by_scope).delete()
        WorkflowDraft.objects.filter(**by_org).delete()
        # Projects now cascade scenarios, aliases, and consumer bindings.
        AIProject.objects.filter(**by_org).delete()
        ToolBinding.objects.filter(**by_org).delete()
        ToolDefinition.objects.filter(**by_org).delete()
        ArtifactVersion.objects.filter(**by_org).delete()
        Consumer.objects.filter(**by_org).delete()
        OrganizationMembership.objects.filter(**by_org).delete()
        org.delete()

    # --- operators ----------------------------------------------------------

    def _ensure_operators(self, org: Organization, password: str) -> None:
        for username, role, is_superuser in OPERATORS:
            user, _ = User.objects.get_or_create(username=username)
            user.is_staff = is_superuser
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()
            OrganizationMembership.objects.get_or_create(
                organization=org, user=user, defaults={"role": role}
            )

    # --- RAG scenario -------------------------------------------------------

    def _ensure_rag(self, org: Organization, project: AIProject) -> None:
        scenario, created = Scenario.objects.get_or_create(
            project=project,
            slug="customer-information",
            defaults={
                "name": "Customer Information",
                "type": ScenarioType.RAG,
                "status": LifecycleStatus.ACTIVE,
            },
        )
        if not created:
            return
        ScenarioAlias.objects.get_or_create(
            organization=org, alias="customer-information", defaults={"scenario": scenario}
        )
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.INPUT_CONTRACT,
            logical_id="customer_query",
            body={
                "type": "object",
                "required": ["query"],
                "additionalProperties": False,
                "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 8000}},
            },
            created_by="editor",
        )
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.OUTPUT_CONTRACT,
            logical_id="customer_answer",
            body={
                "type": "object",
                "required": ["answer", "sources"],
                "additionalProperties": True,
                "properties": {
                    "answer": {"type": "string"},
                    "sources": {"type": "array"},
                    "fallback_used": {"type": "boolean"},
                },
            },
            created_by="editor",
        )
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.MODEL_PROFILE,
            logical_id="default_chat",
            body={"profile_id": "00000000-0000-0000-0000-000000000001"},
            created_by="editor",
        )
        release = compile_release(
            scenario=scenario,
            refs=[
                ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 1),
                ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "customer_answer", 1),
                ArtifactRef("model_profile", ArtifactType.MODEL_PROFILE, "default_chat", 1),
            ],
            runtime_version="rag:1",
            created_by="editor",
        )
        promote_release(release)

    # --- workflow scenario (with a high-risk approval-gated tool) -----------

    def _ensure_workflow(self, org: Organization, project: AIProject) -> None:
        scenario, created = Scenario.objects.get_or_create(
            project=project,
            slug="support-flow",
            defaults={
                "name": "Support Flow",
                "type": ScenarioType.WORKFLOW,
                "status": LifecycleStatus.ACTIVE,
            },
        )
        if not created:
            return
        ScenarioAlias.objects.get_or_create(
            organization=org, alias="support-flow", defaults={"scenario": scenario}
        )
        # Contract logical_ids must match the tool definition's input/output_contract_ref
        # ("tool_in:v1" / "tool_out:v1") so the proxy can resolve them at call time.
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.INPUT_CONTRACT,
            logical_id="tool_in",
            body={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            created_by="editor",
        )
        contract = create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.OUTPUT_CONTRACT,
            logical_id="tool_out",
            body={
                "type": "object",
                "properties": {"status": {"type": "string"}, "echo": {"type": "object"}},
                "required": ["status"],
                "additionalProperties": True,
            },
            created_by="editor",
        )
        register_tool_definition(
            artifact=create_artifact_version(
                organization=org,
                artifact_type=ArtifactType.TOOL_DEFINITION,
                logical_id="search",
                body=_tool_definition_body(),
                created_by="platform",
            )
        )
        binding = create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.TOOL_BINDING,
            logical_id="search_binding",
            body=_tool_binding_body(),
            created_by="editor",
        )
        register_tool_binding(artifact=binding)
        workflow = create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id="support_flow",
            body=_workflow_body(),
            created_by="editor",
        )
        release = compile_release(
            scenario=scenario,
            refs=[
                ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "tool_in", 1),
                ArtifactRef("output_contract", contract.type, "tool_out", 1),
                ArtifactRef("workflow_definition", workflow.type, "support_flow", 1),
                ArtifactRef("tool_binding.search", binding.type, "search_binding", 1),
            ],
            runtime_version="workflow:1",
            created_by="editor",
        )
        promote_release(release)

    # --- agent scenario -----------------------------------------------------

    def _ensure_agent(self, org: Organization, project: AIProject) -> None:
        scenario, created = Scenario.objects.get_or_create(
            project=project,
            slug="assistant",
            defaults={
                "name": "Assistant",
                "type": ScenarioType.AGENT,
                "status": LifecycleStatus.ACTIVE,
            },
        )
        if not created:
            return
        ScenarioAlias.objects.get_or_create(
            organization=org, alias="assistant", defaults={"scenario": scenario}
        )
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.INPUT_CONTRACT,
            logical_id="agent_in",
            body={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
                "additionalProperties": True,
            },
            created_by="editor",
        )
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.OUTPUT_CONTRACT,
            logical_id="agent_out",
            body={
                "type": "object",
                "required": ["answer", "sources"],
                "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
                "additionalProperties": True,
            },
            created_by="editor",
        )
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.AGENT_DEFINITION,
            logical_id="assistant",
            body={
                "api_version": "agenthub/v1",
                "kind": "Agent",
                "metadata": {"id": "assistant.v1", "owner": "editor"},
                "spec": {"tools": []},
            },
            created_by="editor",
        )
        release = compile_release(
            scenario=scenario,
            refs=[
                ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "agent_in", 1),
                ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "agent_out", 1),
                ArtifactRef("agent_definition", ArtifactType.AGENT_DEFINITION, "assistant", 1),
            ],
            runtime_version="agent:1",
            created_by="editor",
        )
        promote_release(release)

    # --- consumer + bindings ------------------------------------------------

    def _ensure_consumer(self, org: Organization) -> Consumer:
        consumer, _ = Consumer.objects.get_or_create(
            organization=org,
            subject=CONSUMER_SUBJECT,
            defaults={"name": "Demo Client", "protocol": ConsumerProtocol.REST},
        )
        bindings = {
            "customer-information": [Capability.QUERY],
            "support-flow": [
                Capability.WORKFLOW_RUN,
                Capability.TOOL_CALL,
                Capability.TOOL_CALL_SIDE_EFFECT,
            ],
            "assistant": [Capability.AGENT_INVOKE],
        }
        for slug, caps in bindings.items():
            scenario = Scenario.objects.filter(project__organization=org, slug=slug).first()
            if scenario is not None:
                ConsumerBinding.objects.get_or_create(
                    consumer=consumer,
                    scenario=scenario,
                    defaults={"capabilities": list(caps)},
                )
        return consumer

    # --- report -------------------------------------------------------------

    def _report(self, password: str, raw_token: str) -> None:
        out = self.stdout
        out.write(self.style.SUCCESS("Demo tenant seeded."))
        out.write("")
        out.write("Operator console  : http://127.0.0.1:8000/console/")
        out.write(f"Operator password : {password}   (all accounts below)")
        out.write("  admin     - platform admin (superuser): sees/does everything")
        out.write("  editor    - scenario_editor: authors artifacts + workflow drafts")
        out.write("  releaser  - release_manager: compile/promote/rollback/canary")
        out.write("  approver  - approver: decides tool approvals")
        out.write("  auditor   - auditor: read-only")
        out.write("")
        out.write("Consumer API bearer token (shown once):")
        out.write(f"  {raw_token}")
        out.write("")
        out.write("Scenario aliases (POST to /v1/):")
        out.write("  customer-information  query    -> POST /v1/query")
        out.write("  support-flow          workflow -> POST /v1/invoke  (pauses for approval)")
        out.write("  assistant             agent    -> POST /v1/invoke")


# --- shared bodies (mirror the verified Sprint 8/9 tool-node test fixtures) --


def _workflow_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "support_flow.v1"},
        "spec": {
            "input_node": "req",
            "nodes": [
                {"id": "req", "type": "input"},
                {
                    "id": "call",
                    "type": "tool",
                    "config": {
                        "binding_role": "tool_binding.search",
                        "input_key": "input",
                        "output_key": "output",
                    },
                },
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "req", "to": "call"},
                {"from": "call", "to": "done"},
            ],
        },
    }


def _tool_definition_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "search.v1", "owner": "platform"},
        "spec": {
            "protocol": "http",
            "destination": {"scheme": "https", "host": "api.example.com"},
            "method": "POST",
            "input_contract_ref": "tool_in:v1",
            "output_contract_ref": "tool_out:v1",
            "risk": "high",
            "side_effecting": True,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": [ORG_SLUG],
        },
    }


def _tool_binding_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "search-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "search:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["status", "echo"],
            "approval": {
                "required": True,
                "approver_roles": ["approver"],
                "self_approval_allowed": False,
            },
        },
    }
