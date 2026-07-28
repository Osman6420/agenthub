"""Seed a disposable local tenant with the three canonical workflow starters."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.roles import Role
from apps.identity.tokens import create_token
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.presets import (
    agent_loop_workflow,
    document_answer_workflow,
    empty_workflow,
)

User = get_user_model()

ORG_SLUG = "demo"
CONSUMER_SUBJECT = "demo-client"
MCP_CONSUMER_SUBJECT = "demo-mcp-client"
OPERATORS = (
    ("admin", Role.ORGANIZATION_ADMIN, True),
    ("editor", Role.SCENARIO_EDITOR, False),
    ("releaser", Role.RELEASE_MANAGER, False),
    ("approver", Role.APPROVER, False),
    ("auditor", Role.AUDITOR, False),
)


class Command(BaseCommand):
    help = "Seed a disposable local workflow demo tenant."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--password", default="")
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        password = str(options["password"] or secrets.token_urlsafe(9))
        with transaction.atomic():
            if options["reset"]:
                self._reset()
            organization, _created = Organization.objects.get_or_create(
                slug=ORG_SLUG,
                defaults={"name": "Demo Org"},
            )
            self._ensure_operators(organization, password)
            project, _created = AIProject.objects.get_or_create(
                organization=organization,
                slug="workflows",
                defaults={"name": "Workflow demos"},
            )
            scenarios = (
                self._ensure_scenario(
                    organization,
                    project,
                    slug="empty-workflow",
                    name="Empty Workflow",
                    workflow_factory=lambda: empty_workflow(logical_id="empty.v1"),
                ),
                self._ensure_scenario(
                    organization,
                    project,
                    slug="document-answer",
                    name="Document Answer",
                    workflow_factory=lambda: document_answer_workflow(
                        logical_id="document_answer.v1"
                    ),
                ),
                self._ensure_scenario(
                    organization,
                    project,
                    slug="agent-loop",
                    name="Agent Loop",
                    workflow_factory=lambda: agent_loop_workflow(
                        logical_id="agent_loop.v1",
                        policy={
                            "tool_binding_roles": [],
                            "retrieval": {"enabled": False},
                            "limits": {
                                "max_steps": 4,
                                "max_tool_calls": 0,
                                "max_tokens": 4096,
                                "deadline_seconds": 60,
                            },
                        },
                    ),
                ),
            )
            rest = self._ensure_consumer(
                organization,
                subject=CONSUMER_SUBJECT,
                name="Demo REST client",
                protocol=ConsumerProtocol.REST,
                scenarios=scenarios,
            )
            mcp = self._ensure_consumer(
                organization,
                subject=MCP_CONSUMER_SUBJECT,
                name="Demo MCP client",
                protocol=ConsumerProtocol.MCP,
                scenarios=scenarios,
            )
            _, rest_token = create_token(rest, f"demo-rest-{secrets.token_hex(3)}")
            _, mcp_token = create_token(mcp, f"demo-mcp-{secrets.token_hex(3)}")

        self.stdout.write(self.style.SUCCESS("Demo workflow tenant ready."))
        self.stdout.write(f"operator password: {password}")
        self.stdout.write(f"REST token: {rest_token}")
        self.stdout.write(f"MCP token: {mcp_token}")
        self.stdout.write("Canonical API: POST /v1/responses")

    def _reset(self) -> None:
        organization = Organization.objects.filter(slug=ORG_SLUG).first()
        if organization is None:
            return
        from apps.artifacts.models import ArtifactVersion
        from apps.builder.models import WorkflowDraft
        from apps.evaluations.models import EvalRun
        from apps.releases.models import ReleaseCanary, ScenarioRelease
        from apps.tools.models import ApprovalRequest, ToolBinding, ToolDefinition, ToolInvocation
        from apps.workflows.models import Run, WorkflowVersion

        ApprovalRequest.objects.filter(organization=organization).delete()
        ToolInvocation.objects.filter(organization=organization).delete()
        Run.objects.filter(organization=organization).delete()
        ReleaseCanary.objects.filter(scenario__project__organization=organization).delete()
        EvalRun.objects.filter(organization=organization).delete()
        ScenarioRelease.objects.filter(scenario__project__organization=organization).delete()
        WorkflowVersion.objects.filter(organization=organization).delete()
        WorkflowDraft.objects.filter(organization=organization).delete()
        ToolBinding.objects.filter(organization=organization).delete()
        ToolDefinition.objects.filter(organization=organization).delete()
        ArtifactVersion.objects.filter(organization=organization).delete()
        Consumer.objects.filter(organization=organization).delete()
        OrganizationMembership.objects.filter(organization=organization).delete()
        AIProject.objects.filter(organization=organization).delete()
        organization.delete()

    @staticmethod
    def _ensure_operators(organization: Organization, password: str) -> None:
        for username, role, is_superuser in OPERATORS:
            user, _created = User.objects.get_or_create(username=username)
            user.is_staff = is_superuser
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()
            OrganizationMembership.objects.update_or_create(
                organization=organization,
                user=user,
                defaults={"role": role},
            )

    @staticmethod
    def _ensure_scenario(
        organization: Organization,
        project: AIProject,
        *,
        slug: str,
        name: str,
        workflow_factory: Callable[[], dict[str, Any]],
    ) -> Scenario:
        scenario, _created = Scenario.objects.update_or_create(
            project=project,
            slug=slug,
            defaults={"name": name, "status": LifecycleStatus.ACTIVE},
        )
        ScenarioAlias.objects.update_or_create(
            organization=organization,
            alias=slug,
            defaults={"scenario": scenario},
        )
        if scenario.releases.filter(status="active").exists():
            return scenario
        input_contract = create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.INPUT_CONTRACT,
            logical_id=f"{slug}.input",
            body={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string", "minLength": 1}},
                "additionalProperties": True,
            },
            created_by="editor",
        )
        output_contract = create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.OUTPUT_CONTRACT,
            logical_id=f"{slug}.output",
            body={
                "type": "object",
                "required": ["answer", "sources"],
                "properties": {
                    "answer": {"type": "string"},
                    "sources": {"type": "array"},
                },
                "additionalProperties": True,
            },
            created_by="editor",
        )
        workflow = create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id=f"{slug}.workflow",
            body=workflow_factory(),
            created_by="editor",
        )
        release = compile_release(
            scenario=scenario,
            refs=[
                ArtifactRef(
                    "input_contract",
                    input_contract.type,
                    input_contract.logical_id,
                    input_contract.version,
                ),
                ArtifactRef(
                    "output_contract",
                    output_contract.type,
                    output_contract.logical_id,
                    output_contract.version,
                ),
                ArtifactRef(
                    "workflow_definition",
                    workflow.type,
                    workflow.logical_id,
                    workflow.version,
                ),
            ],
            runtime_version="workflow:1",
            created_by="releaser",
        )
        promote_release(release)
        return scenario

    @staticmethod
    def _ensure_consumer(
        organization: Organization,
        *,
        subject: str,
        name: str,
        protocol: str,
        scenarios: tuple[Scenario, ...],
    ) -> Consumer:
        consumer, _created = Consumer.objects.update_or_create(
            organization=organization,
            subject=subject,
            defaults={"name": name, "protocol": protocol},
        )
        for scenario in scenarios:
            ConsumerBinding.objects.update_or_create(
                consumer=consumer,
                scenario=scenario,
                defaults={
                    "organization": organization,
                    "capabilities": [Capability.WORKFLOW_RUN],
                    "status": "active",
                },
            )
        return consumer
