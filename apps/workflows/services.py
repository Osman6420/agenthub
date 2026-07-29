"""Workflow compilation services enforcing tenant and artifact boundaries."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.catalog.models import Scenario
from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role, get_manifest_role
from apps.tenancy.context import set_tenant_context
from apps.workflows.compiler import COMPILER_VERSION, WorkflowCompileError, compile_workflow
from apps.workflows.models import (
    CustomNodeDefinition,
    CustomNodeStatus,
    Run,
    RunEventType,
    RunExecutionMode,
    RunStatus,
    WorkflowVersion,
)

MAX_STATE_BYTES = 1_048_576
RUN_TIMEOUT_SECONDS = 300


class WorkflowRequestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@transaction.atomic
def compile_workflow_version(
    *, scenario: Scenario, source_artifact: ArtifactVersion, created_by: str
) -> WorkflowVersion:
    organization_id = scenario.project.organization_id
    if source_artifact.organization_id != organization_id:
        raise WorkflowCompileError("workflow artifact belongs to another organization")
    if source_artifact.type != ArtifactType.WORKFLOW_DEFINITION:
        raise WorkflowCompileError("source artifact is not a workflow definition")

    allowed_refs = frozenset(
        f"{item.logical_id}.v{item.version}"
        for item in CustomNodeDefinition.objects.filter(
            organization_id=organization_id,
            status=CustomNodeStatus.ACTIVE,
        )
    )
    compiled = compile_workflow(source_artifact.body, allowed_custom_nodes=allowed_refs)
    existing = WorkflowVersion.objects.filter(
        scenario=scenario,
        source_artifact=source_artifact,
        compiler_version=COMPILER_VERSION,
    ).first()
    if existing is not None:
        if existing.checksum != compiled.checksum:
            raise WorkflowCompileError("compiled workflow checksum conflict")
        return existing
    return WorkflowVersion.objects.create(
        organization_id=organization_id,
        scenario=scenario,
        source_artifact=source_artifact,
        compiled_graph=compiled.graph,
        checksum=compiled.checksum,
        compiler_version=COMPILER_VERSION,
        created_by=created_by,
    )


@transaction.atomic
def register_custom_node_definition(
    *, artifact: ArtifactVersion, installed_package_version: str
) -> CustomNodeDefinition:
    if artifact.type != ArtifactType.CUSTOM_NODE_DEFINITION:
        raise WorkflowCompileError("artifact is not a custom node definition")
    manifest = artifact.body
    spec = manifest.get("spec", {})
    if artifact.organization.slug not in spec.get("allowed_organizations", []):
        raise WorkflowCompileError("custom node is not allowed for this organization")
    if str(spec.get("package_version", "")) != installed_package_version:
        raise WorkflowCompileError("installed custom node package version does not match")
    existing = CustomNodeDefinition.objects.filter(
        organization=artifact.organization,
        logical_id=artifact.logical_id,
        version=artifact.version,
    ).first()
    if existing is not None:
        return existing
    return CustomNodeDefinition.objects.create(
        organization=artifact.organization,
        logical_id=artifact.logical_id,
        version=artifact.version,
        manifest=manifest,
        checksum=artifact.checksum,
        installed_package_version=installed_package_version,
    )


def resolve_release_workflow(release: ScenarioRelease) -> WorkflowVersion:
    entry = get_manifest_role(release, "workflow_definition")
    body = get_artifact_body_for_role(release, "workflow_definition")
    if entry is None or body is None:
        raise WorkflowCompileError("release does not pin a workflow definition")
    ref = str(entry.get("ref", ""))
    if ":v" not in ref:
        raise WorkflowCompileError("release workflow reference is invalid")
    logical_id, _, version_text = ref.rpartition(":v")
    if not version_text.isdigit():
        raise WorkflowCompileError("release workflow reference is invalid")
    artifact = ArtifactVersion.objects.filter(
        organization_id=release.scenario.project.organization_id,
        type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id=logical_id,
        version=int(version_text),
        checksum=str(entry.get("checksum", "")),
    ).first()
    if artifact is None:
        raise WorkflowCompileError("release workflow artifact is unresolved")
    return compile_workflow_version(
        scenario=release.scenario,
        source_artifact=artifact,
        created_by="release-runtime",
    )


@transaction.atomic
def request_unified_run(
    *,
    release: ScenarioRelease,
    consumer: Consumer,
    workflow_version: WorkflowVersion,
    execution_context: dict[str, Any],
    input_payload: dict[str, Any],
    idempotency_key: str,
    execution_mode: str,
) -> tuple[Run, bool]:
    """Admit one exact-pinned Run without trusting client-carried authority."""

    if not idempotency_key or len(idempotency_key) > 128:
        raise WorkflowRequestError("IDEMPOTENCY_KEY_REQUIRED")
    try:
        mode = RunExecutionMode(execution_mode)
    except ValueError:
        raise WorkflowRequestError("UNSUPPORTED_EXECUTION_MODE") from None
    analysis = workflow_version.compiled_graph.get("execution_mode_analysis")
    supported_modes = (
        analysis.get("supported_execution_modes") if isinstance(analysis, dict) else None
    )
    if (
        not isinstance(supported_modes, list)
        or any(not isinstance(item, str) for item in supported_modes)
        or mode not in supported_modes
    ):
        raise WorkflowRequestError("UNSUPPORTED_EXECUTION_MODE")

    organization_id = consumer.organization_id
    set_tenant_context(organization_id)
    try:
        verified_context = verify_execution_context(execution_context)
    except ExecutionContextInvalid:
        raise WorkflowRequestError("EXECUTION_CONTEXT_INVALID") from None
    scenario = release.scenario
    context_capabilities = verified_context.get("capabilities")
    if (
        scenario.project.organization_id != organization_id
        or workflow_version.organization_id != organization_id
        or workflow_version.scenario_id != scenario.id
        or verified_context.get("organization_id") != organization_id
        or verified_context.get("project_id") != scenario.project_id
        or verified_context.get("scenario_id") != scenario.id
        or verified_context.get("consumer_id") != consumer.id
        or verified_context.get("release_id") != release.id
        or not isinstance(context_capabilities, list)
        or any(not isinstance(item, str) for item in context_capabilities)
        or Capability.WORKFLOW_RUN not in context_capabilities
    ):
        raise WorkflowRequestError("EXECUTION_CONTEXT_INVALID")
    input_checksum = compute_checksum(input_payload)
    existing = (
        Run.objects.select_for_update()
        .filter(consumer=consumer, idempotency_key=idempotency_key)
        .first()
    )
    if existing is not None:
        if (
            existing.input_checksum != input_checksum
            or existing.release_id != release.id
            or existing.workflow_version_id != workflow_version.id
            or existing.execution_mode != mode
            or not existing.response_id
        ):
            raise WorkflowRequestError("IDEMPOTENCY_CONFLICT")
        return existing, False

    from apps.agents.services import observe_runtime_suspension, runtime_suspended

    if runtime_suspended(
        organization_id,
        project_id=scenario.project_id,
        scenario_id=scenario.id,
    ):
        observe_runtime_suspension("admission")
        raise WorkflowRequestError("RUN_RUNTIME_SUSPENDED")

    state = {"input": input_payload}
    _assert_state_size(state)
    run = Run(
        organization_id=organization_id,
        scenario=release.scenario,
        release=release,
        workflow_version=workflow_version,
        consumer=consumer,
        actor_id=consumer.subject,
        response_id=f"resp_{uuid.uuid4().hex}",
        idempotency_key=idempotency_key,
        compiled_checksum=workflow_version.checksum,
        compiler_version=workflow_version.compiler_version,
        execution_mode=mode,
        checkpoint=state,
        deadline_at=timezone.now() + timedelta(seconds=RUN_TIMEOUT_SECONDS),
        input_checksum=input_checksum,
        execution_context=execution_context,
        redacted_state=redact_run_state(state),
    )
    run.full_clean(validate_unique=False)
    try:
        with transaction.atomic():
            run.save()
    except IntegrityError:
        winner = (
            Run.objects.select_for_update()
            .filter(consumer=consumer, idempotency_key=idempotency_key)
            .first()
        )
        if winner is None:
            raise
        if (
            winner.input_checksum != input_checksum
            or winner.release_id != release.id
            or winner.workflow_version_id != workflow_version.id
            or winner.execution_mode != mode
            or not winner.response_id
        ):
            raise WorkflowRequestError("IDEMPOTENCY_CONFLICT") from None
        return winner, False

    from apps.workflows.run_events import append_locked_run_event
    from apps.workflows.transitions import transition_run

    append_locked_run_event(
        run=run,
        event_type=RunEventType.REQUESTED,
        outcome=RunStatus.REQUESTED,
        state_checksum=compute_checksum(state),
        payload={"execution_mode": str(mode)},
    )
    run.save(update_fields=["next_event_sequence", "updated_at"])
    transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=uuid.uuid5(run.id, "admission:queued"),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=RunStatus.REQUESTED,
        target_status=RunStatus.QUEUED,
    )
    run.refresh_from_db()
    return run, True


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return "[redacted]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "[redacted]"


def redact_run_state(state: dict[str, Any]) -> dict[str, Any]:
    """Project a checkpoint into the bounded operator/API-safe state view.

    Governed terminal output is already contract/policy checked and must remain available to
    callers. Input, evidence, branch state and internal resume cursors may contain prompts,
    document text or tool/model bodies, so their string values are redacted recursively.
    """

    projected: dict[str, Any] = {}
    for key, value in state.items():
        if key == "output" and isinstance(value, dict):
            projected[key] = value
        else:
            projected[key] = _redact(value)
    return projected


def _assert_state_size(state: dict[str, Any]) -> None:
    size = len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > MAX_STATE_BYTES:
        raise WorkflowRequestError("WORKFLOW_STATE_TOO_LARGE")
