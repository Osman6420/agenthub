"""Workflow compilation services enforcing tenant and artifact boundaries."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.catalog.models import Scenario
from apps.gateway.execution_context import verify_execution_context
from apps.identity.models import Consumer
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role, get_manifest_role
from apps.workflows.compiler import COMPILER_VERSION, WorkflowCompileError, compile_workflow
from apps.workflows.models import (
    CustomNodeDefinition,
    CustomNodeStatus,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStatus,
    WorkflowVersion,
    WorkflowWaitStatus,
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
def request_workflow_run(
    *,
    release: ScenarioRelease,
    consumer: Consumer,
    workflow_version: WorkflowVersion,
    execution_context: dict[str, Any],
    input_payload: dict[str, Any],
    idempotency_key: str,
) -> tuple[WorkflowRun, bool]:
    if not idempotency_key or len(idempotency_key) > 128:
        raise WorkflowRequestError("IDEMPOTENCY_KEY_REQUIRED")
    verify_execution_context(execution_context)
    input_checksum = compute_checksum(input_payload)
    existing = (
        WorkflowRun.objects.select_for_update()
        .filter(consumer=consumer, idempotency_key=idempotency_key)
        .first()
    )
    if existing is not None:
        if existing.input_checksum != input_checksum or existing.release_id != release.id:
            raise WorkflowRequestError("IDEMPOTENCY_CONFLICT")
        return existing, False

    state = {"input": _redact(input_payload)}
    _assert_state_size(state)
    run = WorkflowRun(
        organization_id=consumer.organization_id,
        scenario=release.scenario,
        release=release,
        workflow_version=workflow_version,
        consumer=consumer,
        idempotency_key=idempotency_key,
        input_checksum=input_checksum,
        execution_context=execution_context,
        redacted_state=state,
        status=WorkflowRunStatus.QUEUED,
        deadline_at=timezone.now() + timedelta(seconds=RUN_TIMEOUT_SECONDS),
    )
    run.full_clean()
    try:
        with transaction.atomic():
            run.save()
    except IntegrityError:
        winner = WorkflowRun.objects.get(consumer=consumer, idempotency_key=idempotency_key)
        if winner.input_checksum != input_checksum or winner.release_id != release.id:
            raise WorkflowRequestError("IDEMPOTENCY_CONFLICT") from None
        return winner, False
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=1,
        event_type="run_queued",
        outcome="queued",
        state_checksum=compute_checksum(state),
    )
    return run, True


@transaction.atomic
def cancel_workflow_run(*, run: WorkflowRun, consumer: Consumer) -> WorkflowRun:
    locked = WorkflowRun.objects.select_for_update().get(pk=run.pk)
    if locked.consumer_id != consumer.id or locked.organization_id != consumer.organization_id:
        raise WorkflowRequestError("RUN_NOT_FOUND")
    if locked.status in {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
    }:
        return locked
    if locked.status != WorkflowRunStatus.CANCELLED:
        locked.status = WorkflowRunStatus.CANCELLED
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "finished_at", "updated_at"])
        WorkflowRunEvent.objects.create(
            run=locked,
            sequence=_next_sequence(locked),
            event_type="run_cancelled",
            outcome="cancelled",
        )
        # Typed branch/join records are durable work admission state. Cancellation closes them
        # in the same transaction; late worker results then observe terminal guards.
        from apps.workflows.parallel import cancel_parallel_work

        cancel_parallel_work(organization_id=locked.organization_id, run_id=locked.id)
        locked.waits.filter(status=WorkflowWaitStatus.PENDING).update(
            status=WorkflowWaitStatus.CANCELLED,
            consumed_at=timezone.now(),
            updated_at=timezone.now(),
        )
    return locked


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


def _assert_state_size(state: dict[str, Any]) -> None:
    size = len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > MAX_STATE_BYTES:
        raise WorkflowRequestError("WORKFLOW_STATE_TOO_LARGE")


def _next_sequence(run: WorkflowRun) -> int:
    latest = run.events.order_by("-sequence").values_list("sequence", flat=True).first()
    return int(latest or 0) + 1
