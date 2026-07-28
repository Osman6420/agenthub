"""Pinned, tenant-safe child workflow execution for canonical Runs."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from django.db import transaction

from apps.artifacts.validation import compute_checksum
from apps.gateway.execution_context import (
    ExecutionContextInvalid,
    issue_execution_context,
    verify_execution_context,
)
from apps.identity.capabilities import Capability
from apps.identity.models import BindingStatus, ConsumerBinding
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.releases.services import get_manifest_role
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import (
    RUN_TERMINAL_STATUSES,
    Run,
    RunAwaitingKind,
    RunChildLink,
    RunChildStatus,
    RunEventType,
    RunExecutionMode,
    RunStatus,
)
from apps.workflows.run_events import append_locked_run_event
from apps.workflows.services import (
    WorkflowRequestError,
    request_unified_run,
    resolve_release_workflow,
)
from apps.workflows.state_mapping import MappingError, apply_output_mapping
from apps.workflows.transitions import transition_run

MAX_COMPOSITION_DEPTH = 3
MAX_CHILDREN_PER_PARENT = 8


class RunChildError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _parent_claim(parent: Run) -> dict[str, Any]:
    try:
        payload = verify_execution_context(parent.execution_context)
    except ExecutionContextInvalid:
        raise RunChildError("EXECUTION_CONTEXT_INVALID") from None
    claim = payload.get("composition")
    if isinstance(claim, dict):
        return {
            "depth": int(claim.get("depth", 0)),
            "ancestry": [int(item) for item in claim.get("ancestry", [])],
            "root_run": str(claim.get("root_run", parent.id)),
            "capabilities": payload.get("capabilities", []),
            "request_id": str(payload.get("request_id", "")),
        }
    return {
        "depth": 0,
        "ancestry": [parent.scenario_id],
        "root_run": str(parent.id),
        "capabilities": payload.get("capabilities", []),
        "request_id": str(payload.get("request_id", "")),
    }


def _resolve_child(parent: Run, node: dict[str, Any]) -> tuple[ScenarioRelease, dict[str, Any]]:
    role = f"child_workflow.{node['config']['workflow_role']}"
    entry = get_manifest_role(parent.release, role)
    if not isinstance(entry, dict):
        raise RunChildError("COMPOSITION_CHILD_UNPINNED")
    pin = entry.get("child")
    if not isinstance(pin, dict):
        raise RunChildError("COMPOSITION_CHILD_UNPINNED")
    release_id = pin.get("release_id")
    if not isinstance(release_id, int):
        raise RunChildError("COMPOSITION_CHILD_UNPINNED")
    release = (
        ScenarioRelease.objects.select_related("scenario", "scenario__project")
        .filter(
            pk=release_id,
            organization_id=parent.organization_id,
            status=ReleaseStatus.ACTIVE,
        )
        .first()
    )
    if release is None:
        raise RunChildError("COMPOSITION_CHILD_UNRESOLVED")
    if (
        release.scenario_id != pin.get("scenario_id")
        or release.artifact_manifest_sha256 != pin.get("release_checksum")
        or entry.get("checksum") != pin.get("artifact_checksum")
    ):
        raise RunChildError("COMPOSITION_CHILD_STALE")
    return release, pin


def _effective_capabilities(parent: Run, child_release: ScenarioRelease) -> list[str]:
    binding = ConsumerBinding.objects.filter(
        consumer=parent.consumer,
        scenario=child_release.scenario,
        status=BindingStatus.ACTIVE,
    ).first()
    if binding is None:
        raise RunChildError("COMPOSITION_AUTHORITY_DENIED")
    claim = _parent_claim(parent)
    effective = {str(item) for item in claim["capabilities"]} & {
        str(item) for item in binding.capabilities
    }
    if Capability.WORKFLOW_RUN not in effective:
        raise RunChildError("COMPOSITION_AUTHORITY_DENIED")
    return sorted(effective)


@transaction.atomic
def admit_run_child(
    *,
    parent_run: Run,
    node: dict[str, Any],
    input_envelope: dict[str, Any],
) -> RunChildLink:
    """Create one exact child Run and immutable link for a parent call site."""

    set_tenant_context(parent_run.organization_id)
    parent = (
        Run.objects.select_for_update()
        .select_related("consumer", "release", "scenario")
        .get(pk=parent_run.id, organization_id=parent_run.organization_id)
    )
    node_id = str(node["id"])
    existing = RunChildLink.objects.filter(parent_run=parent, call_site=node_id).first()
    if existing is not None:
        return existing
    if RunChildLink.objects.filter(parent_run=parent).count() >= MAX_CHILDREN_PER_PARENT:
        raise RunChildError("COMPOSITION_MAX_CHILDREN")

    child_release, pin = _resolve_child(parent, node)
    claim = _parent_claim(parent)
    depth = int(claim["depth"]) + 1
    if depth > min(MAX_COMPOSITION_DEPTH, int(node["config"]["max_depth"])):
        raise RunChildError("COMPOSITION_MAX_DEPTH")
    ancestry = list(claim["ancestry"])
    if child_release.scenario_id in ancestry:
        raise RunChildError("COMPOSITION_CYCLE")
    payload = input_envelope.get("input")
    if not isinstance(payload, dict):
        raise RunChildError("COMPOSITION_CHILD_INPUT_INVALID")

    capabilities = _effective_capabilities(parent, child_release)
    child_context = issue_execution_context(
        organization_id=parent.organization_id,
        project_id=child_release.scenario.project_id,
        scenario_id=child_release.scenario_id,
        scenario_alias=f"composition:{parent.id}:{node_id}",
        consumer_id=parent.consumer_id,
        capabilities=capabilities,
        release_id=child_release.id,
        request_id=claim["request_id"],
        composition={
            "depth": depth,
            "ancestry": [*ancestry, child_release.scenario_id],
            "root_run": claim["root_run"],
            "parent_run": str(parent.id),
        },
    )
    try:
        child, created = request_unified_run(
            release=child_release,
            consumer=parent.consumer,
            workflow_version=resolve_release_workflow(child_release),
            execution_context=child_context,
            input_payload=payload,
            idempotency_key=f"child:{parent.id}:{node_id}",
            execution_mode=RunExecutionMode.BACKGROUND,
        )
    except WorkflowRequestError as exc:
        raise RunChildError(exc.code) from None
    link = RunChildLink(
        organization_id=parent.organization_id,
        parent_run=parent,
        child_run=child,
        call_site=node_id,
        child_release_checksum=child_release.artifact_manifest_sha256,
        child_artifact_checksum=str(pin["artifact_checksum"]),
        effective_capability_checksum=compute_checksum(capabilities),
        depth=depth,
    )
    link.full_clean()
    link.save()
    append_locked_run_event(
        run=parent,
        event_type=RunEventType.CHILD_ADMITTED,
        node_id=node_id,
        outcome=RunChildStatus.ADMITTED,
        state_checksum=link.effective_capability_checksum,
        payload={"depth": depth},
    )
    parent.save(update_fields=["next_event_sequence", "updated_at"])
    if created:
        from apps.workflows.tasks import dispatch_unified_background_run

        transaction.on_commit(
            lambda: dispatch_unified_background_run(
                run_id=child.id, organization_id=parent.organization_id
            )
        )
    return link


@transaction.atomic
def converge_run_child(*, child_run_id: uuid.UUID, organization_id: int) -> bool:
    """Converge one terminal child result into its exact waiting parent once."""

    set_tenant_context(organization_id)
    locator = (
        RunChildLink.objects.filter(
            child_run_id=child_run_id,
            organization_id=organization_id,
            status=RunChildStatus.ADMITTED,
        )
        .values_list("id", "parent_run_id")
        .first()
    )
    if locator is None:
        return False
    link_id, parent_run_id = locator
    parent = Run.objects.select_for_update().get(pk=parent_run_id, organization_id=organization_id)
    link = (
        RunChildLink.objects.select_for_update()
        .filter(
            pk=link_id,
            organization_id=organization_id,
            status=RunChildStatus.ADMITTED,
        )
        .first()
    )
    if link is None:
        return False
    child = Run.objects.select_for_update().get(pk=child_run_id, organization_id=organization_id)
    if child.status not in RUN_TERMINAL_STATUSES:
        return False
    if parent.status in RUN_TERMINAL_STATUSES:
        link.status = RunChildStatus.CANCELLED
        link.reason_code = "PARENT_TERMINAL"
        link.save(update_fields=["status", "reason_code", "updated_at"])
        return False
    expected_reference = str(child.id)
    if (
        parent.status != RunStatus.WAITING_CHILD
        or parent.awaiting_kind != RunAwaitingKind.CHILD
        or parent.awaiting_reference != expected_reference
    ):
        return False

    if child.status == RunStatus.COMPLETED and isinstance(child.checkpoint.get("output"), dict):
        graph_node = next(
            (
                item
                for item in parent.workflow_version.compiled_graph.get("nodes", [])
                if item.get("id") == link.call_site
            ),
            None,
        )
        if not isinstance(graph_node, dict):
            raise RunChildError("COMPOSITION_CHILD_UNRESOLVED")
        try:
            checkpoint = apply_output_mapping(
                deepcopy(parent.checkpoint),
                {"output": deepcopy(child.checkpoint["output"])},
                graph_node["output_mapping"],
            )
        except (KeyError, MappingError):
            target_status = RunStatus.FAILED
            checkpoint = parent.checkpoint
            error_code = "COMPOSITION_CHILD_OUTPUT_INVALID"
            link.status = RunChildStatus.FAILED
        else:
            target_status = RunStatus.QUEUED
            error_code = ""
            link.status = RunChildStatus.COMPLETED
    else:
        target_status = RunStatus.FAILED
        checkpoint = parent.checkpoint
        error_code = "COMPOSITION_CHILD_FAILED"
        link.status = RunChildStatus.FAILED

    link.reason_code = error_code
    link.save(update_fields=["status", "reason_code", "updated_at"])
    append_locked_run_event(
        run=parent,
        event_type=RunEventType.CHILD_COMPLETED,
        node_id=link.call_site,
        outcome=str(link.status),
        reason_code=error_code,
        payload={"child_status": str(child.status)},
    )
    parent.save(update_fields=["next_event_sequence", "updated_at"])
    transitioned = transition_run(
        organization_id=organization_id,
        run_id=parent.id,
        transition_token=uuid.uuid5(parent.id, f"child-converge:{child.id}"),
        expected_checkpoint_version=parent.checkpoint_version,
        expected_status=RunStatus.WAITING_CHILD,
        target_status=target_status,
        checkpoint=checkpoint,
        error_code=error_code,
    )
    if transitioned.status == RunStatus.QUEUED:
        from apps.workflows.tasks import dispatch_unified_background_run

        transaction.on_commit(
            lambda: dispatch_unified_background_run(
                run_id=parent.id, organization_id=organization_id
            )
        )
    return transitioned.outcome == "committed"
