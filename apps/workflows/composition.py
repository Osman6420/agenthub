"""Pinned sub-workflow / single agent-call composition (P2.6.5 / ADR-0009).

This module is the trust boundary for child composition. A parent workflow node
(``subworkflow``/``agent_call``) may invoke only an *exact* child role pinned into the parent
release manifest. The parent's authorization is **not** delegated: the effective child capability
set is computed server-side as the intersection of four required sources and the child runs as a
**separate** durable run under a **freshly issued, attenuated** execution context, connected to the
parent by an immutable tenant-scoped :class:`~apps.workflows.models.WorkflowChildLink`.

Two entry points:

- :func:`pin_composition_children` — release-compile time. Resolves each composition node's pinned
  child role to an exact same-organization released child scenario/release/checksum and records the
  pin into the manifest. Rejects unpinned, foreign, unreleased, ambiguous or self-cyclic children.
- :func:`admit_child` / :func:`finalize_child` — runtime. ``admit_child`` re-resolves the child
  server-side, re-authorizes all four ADR-0009 sources, enforces depth/child/call/deadline budgets
  and an ancestry/cycle guard, then creates the child run + link under a fresh context.
  ``finalize_child`` validates the untrusted child output before the parent maps it back.

Nothing here trusts workflow state, model output, broker payloads, run/release/link ids, or a
parent's signed context: every decision is resolved from server-owned records and fails closed.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.identity.capabilities import Capability
from apps.releases.services import get_manifest_role
from apps.workflows.models import (
    CHILD_LINK_TERMINAL_STATUSES,
    WORKFLOW_TERMINAL_STATUSES,
    ChildLinkStatus,
    WorkflowChildLink,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStatus,
)

# Conservative initial maxima (plan §Resolved decisions). A call-site may only *lower* depth.
MAX_COMPOSITION_DEPTH = 3
MAX_CHILDREN_PER_PARENT = 8
MAX_CUMULATIVE_CHILD_CALLS = 16
MAX_COMPOSITION_TOKENS = 64_000
MAX_MAPPED_BYTES = 1_048_576
CHILD_RUN_TIMEOUT_SECONDS = 300
CHILD_CONTEXT_TTL_SECONDS = 900

_BASE_CAP = {
    "workflow": Capability.WORKFLOW_RUN.value,
    "agent": Capability.AGENT_INVOKE.value,
}
_ACTION_CAPS: dict[str, frozenset[str]] = {
    "retrieve": frozenset({Capability.QUERY.value}),
    "tool": frozenset({Capability.TOOL_CALL.value, Capability.TOOL_CALL_SIDE_EFFECT.value}),
    # A verification observation re-runs retrieval or a pinned no-side-effect tool only
    # (compiler-guaranteed), so it never needs the side-effecting tool capability (P2.6.6).
    "verify": frozenset({Capability.QUERY.value, Capability.TOOL_CALL.value}),
    "respond": frozenset({Capability.QUERY.value}),
    # ``escalate`` is a safe terminal decision; it grants no additional capability.
    "escalate": frozenset(),
}


class CompositionCompileError(ValueError):
    """Safe, content-free child-composition compile diagnostic."""


class CompositionError(RuntimeError):
    """Runtime child-admission/finalization failure carrying a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CompositionPending(Exception):
    """The child run is not terminal yet; the parent must stay paused."""


# --------------------------------------------------------------------------------------------------
# Compile-time pinning
# --------------------------------------------------------------------------------------------------
def pin_composition_children(
    *, scenario: Any, graph: dict[str, Any], artifacts_manifest: dict[str, dict[str, Any]]
) -> None:
    """Resolve and pin each composition node's exact released child into the manifest.

    Mutates ``artifacts_manifest`` in place, adding a ``child`` pin under each child role.
    Raises :class:`CompositionCompileError` for any unpinned, foreign, unreleased, ambiguous or
    self-cyclic child. This runs only when composition is enabled (a graph cannot contain these
    nodes otherwise), so it never affects composition-free releases.
    """
    from apps.catalog.models import ScenarioType

    organization_id = scenario.project.organization_id
    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") not in {"subworkflow", "agent_call"}:
            continue
        config = node.get("config", {})
        if node["type"] == "subworkflow":
            kind, expected_type, scenario_type = (
                "workflow",
                ArtifactType.WORKFLOW_DEFINITION,
                ScenarioType.WORKFLOW,
            )
            role_name = config.get("workflow_role")
            manifest_role = f"child_workflow.{role_name}"
        else:
            kind, expected_type, scenario_type = (
                "agent",
                ArtifactType.AGENT_DEFINITION,
                ScenarioType.AGENT,
            )
            role_name = config.get("agent_role")
            manifest_role = f"child_agent.{role_name}"

        entry = artifacts_manifest.get(manifest_role)
        if not isinstance(entry, dict) or entry.get("type") != expected_type:
            raise CompositionCompileError(
                f"composition node references an unpinned child role: {manifest_role}"
            )
        pin = _resolve_child_release_pin(
            organization_id=organization_id,
            entry=entry,
            expected_type=expected_type,
            scenario_type=scenario_type,
            parent_scenario_id=scenario.id,
            kind=kind,
        )
        entry["child"] = pin


def _resolve_child_release_pin(
    *,
    organization_id: int,
    entry: dict[str, Any],
    expected_type: str,
    scenario_type: Any,
    parent_scenario_id: int,
    kind: str,
) -> dict[str, Any]:
    from apps.artifacts.models import ArtifactVersion
    from apps.releases.models import ReleaseStatus, ScenarioRelease

    ref = str(entry.get("ref", ""))
    checksum = str(entry.get("checksum", ""))
    if ":v" not in ref:
        raise CompositionCompileError("child reference is invalid")
    logical_id, _, version_text = ref.rpartition(":v")
    if not version_text.isdigit():
        raise CompositionCompileError("child reference is invalid")
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=expected_type,
        logical_id=logical_id,
        version=int(version_text),
        checksum=checksum,
    ).first()
    if artifact is None:
        raise CompositionCompileError("child artifact is unresolved in this organization")

    runtime_role = "workflow_definition" if kind == "workflow" else "agent_definition"
    candidates = []
    for release in (
        ScenarioRelease.objects.filter(organization_id=organization_id, status=ReleaseStatus.ACTIVE)
        .select_related("scenario", "scenario__project")
        .iterator()
    ):
        pinned = release.manifest.get("artifacts", {}).get(runtime_role)
        if (
            isinstance(pinned, dict)
            and pinned.get("ref") == ref
            and pinned.get("checksum") == (checksum)
        ):
            candidates.append(release)
    if not candidates:
        raise CompositionCompileError("child role has no active released scenario")
    if len(candidates) > 1:
        raise CompositionCompileError("child role resolves to multiple releases")
    release = candidates[0]
    if release.scenario_id == parent_scenario_id:
        raise CompositionCompileError("composition cycle: child resolves to the parent scenario")
    if release.scenario.type != scenario_type:
        raise CompositionCompileError("child scenario type does not match the composition node")
    return {
        "kind": kind,
        "scenario_id": release.scenario_id,
        "release_id": release.id,
        "release_checksum": release.artifact_manifest_sha256,
        "artifact_checksum": checksum,
    }


# --------------------------------------------------------------------------------------------------
# Runtime admission
# --------------------------------------------------------------------------------------------------
def admit_child(
    *, parent_run: WorkflowRun, node: dict[str, Any], input_env: dict[str, Any]
) -> None:
    """Admit one child call site: authorize, budget-check, create the child run + link, dispatch.

    Must be called inside the parent run's transaction (the caller holds the parent lock). Raises
    :class:`CompositionError` (fail closed) for any denial; on success it commits the immutable link
    and schedules the child's Celery dispatch after commit. The child run is created with only the
    mapped, schema-valid input and a fresh attenuated execution context.
    """
    if not getattr(settings, "WORKFLOW_COMPOSITION_ENABLED", False):
        raise CompositionError("COMPOSITION_DISABLED")

    node_id = str(node["id"])
    config = node["config"]
    kind = "workflow" if node["type"] == "subworkflow" else "agent"
    organization_id = parent_run.organization_id

    # Idempotent admission: a committed link for this exact call site means the child was already
    # admitted (duplicate dispatch / redelivery). Never admit or re-authorize a second child.
    if WorkflowChildLink.objects.filter(parent_run=parent_run, call_site=node_id).exists():
        return

    payload = _verified_parent_payload(parent_run)
    claim = _parent_claim(payload, parent_run)

    child_scenario, child_release, pin = _resolve_active_child(parent_run, config, kind)

    depth = int(claim["depth"]) + 1
    depth_cap = MAX_COMPOSITION_DEPTH
    if kind == "workflow":
        depth_cap = min(depth_cap, int(config["max_depth"]))
    if depth > depth_cap:
        raise CompositionError("COMPOSITION_MAX_DEPTH")
    ancestry = [int(s) for s in claim["ancestry"]]
    if child_scenario.id in ancestry:
        raise CompositionError("COMPOSITION_CYCLE")
    calls = int(claim["calls"]) + 1
    if calls > MAX_CUMULATIVE_CHILD_CALLS:
        raise CompositionError("COMPOSITION_MAX_CALLS")
    if (
        WorkflowChildLink.objects.filter(parent_run=parent_run).exclude(call_site=node_id).count()
        >= MAX_CHILDREN_PER_PARENT
    ):
        raise CompositionError("COMPOSITION_MAX_CHILDREN")

    effective = _effective_child_capabilities(
        kind=kind,
        node_config=config,
        parent_payload=payload,
        consumer=parent_run.consumer,
        child_scenario=child_scenario,
        child_release=child_release,
    )
    if _BASE_CAP[kind] not in effective:
        raise CompositionError("COMPOSITION_AUTHORITY_DENIED")

    payload_input = input_env.get("input")
    if not isinstance(payload_input, dict):
        raise CompositionError("COMPOSITION_CHILD_INPUT_INVALID")
    _assert_mapped_size(input_env)
    _validate_child_input(child_release, payload_input)

    effective_sorted = sorted(effective)
    cap_checksum = compute_checksum(effective_sorted)
    child_claim = {
        "depth": depth,
        "ancestry": ancestry + [child_scenario.id],
        "calls": calls,
        "root_run": int(claim["root_run"]),
        "parent_run": parent_run.id,
    }
    if kind == "agent":
        child_claim["max_decisions"] = int(config["max_decisions"])
        # Attenuate the child agent's reachable decision kinds to exactly the call-site's
        # authored allowlist (P2.6.6). The child runtime denies any kind outside this set.
        child_claim["allowed_actions"] = sorted(config.get("allowed_actions", []))

    child_context = _issue_child_context(
        parent_run=parent_run,
        node_id=node_id,
        child_scenario=child_scenario,
        child_release=child_release,
        capabilities=effective_sorted,
        request_id=str(payload.get("request_id", "")),
        composition=child_claim,
    )
    deadline = min(
        parent_run.deadline_at, timezone.now() + timedelta(seconds=CHILD_RUN_TIMEOUT_SECONDS)
    )

    if kind == "workflow":
        child_run, created = _create_child_workflow_run(
            parent_run=parent_run,
            node_id=node_id,
            child_scenario=child_scenario,
            child_release=child_release,
            envelope=input_env,
            payload_input=payload_input,
            child_context=child_context,
            deadline=deadline,
        )
    else:
        child_run, created = _create_child_agent_run(
            parent_run=parent_run,
            node_id=node_id,
            child_scenario=child_scenario,
            child_release=child_release,
            payload_input=payload_input,
            child_context=child_context,
            deadline=deadline,
        )

    link = _create_link(
        parent_run=parent_run,
        node_id=node_id,
        kind=kind,
        child_scenario=child_scenario,
        child_release=child_release,
        pin=pin,
        child_run=child_run,
        effective_checksum=cap_checksum,
        depth=depth,
    )
    WorkflowRunEvent.objects.create(
        run=parent_run,
        sequence=_next_sequence(parent_run),
        event_type="child_admitted",
        node_id=node_id,
        outcome="admitted",
        reason_code=kind,
        state_checksum=cap_checksum,
    )
    if created:
        _dispatch_child(kind=kind, child_run_id=child_run.id, organization_id=organization_id)
    _ = link


def finalize_child(*, link: WorkflowChildLink) -> dict[str, Any]:
    """Return the validated child output envelope, or fail closed / signal still-pending.

    The child output is untrusted: it is re-validated against the child release output contract and
    size ceiling and the cumulative-token guard before the parent maps it back. Raises
    :class:`CompositionPending` if the child is not terminal, or :class:`CompositionError` on child
    failure/timeout/cancellation/invalid output.
    """
    if link.status == ChildLinkStatus.FAILED:
        raise CompositionError(link.reason_code or "COMPOSITION_CHILD_FAILED")
    if link.status == ChildLinkStatus.CANCELLED:
        raise CompositionError("COMPOSITION_CHILD_CANCELLED")

    if link.child_kind == "workflow":
        wf_child = WorkflowRun.objects.filter(pk=int(link.child_workflow_run_id or 0)).first()
        if wf_child is None:
            raise CompositionError("COMPOSITION_CHILD_UNRESOLVED")
        if wf_child.status not in WORKFLOW_TERMINAL_STATUSES:
            raise CompositionPending()
        if wf_child.status != WorkflowRunStatus.COMPLETED:
            _mark_link_failed(link, wf_child.status)
            raise CompositionError(_child_fail_code(wf_child.status))
        output = wf_child.redacted_state.get("output")
    else:
        from apps.agents.models import TERMINAL_RUN_STATUSES, AgentRun, AgentRunStatus

        ag_child = (
            AgentRun.objects.select_related("agent_version")
            .filter(pk=int(link.child_agent_run_id or 0))
            .first()
        )
        if ag_child is None:
            raise CompositionError("COMPOSITION_CHILD_UNRESOLVED")
        if ag_child.status not in TERMINAL_RUN_STATUSES:
            raise CompositionPending()
        if ag_child.status != AgentRunStatus.COMPLETED:
            _mark_link_failed(link, ag_child.status)
            raise CompositionError(_child_fail_code(ag_child.status))
        output_key = ag_child.agent_version.compiled_config.get("output_key", "output")
        output = ag_child.checkpoint.get(output_key)

    if not isinstance(output, dict):
        _mark_link_failed(link, "output_invalid")
        raise CompositionError("COMPOSITION_CHILD_OUTPUT_INVALID")
    _assert_mapped_size(output)
    _validate_child_output(link.child_release, output)
    _assert_cumulative_tokens(link)

    if link.status != ChildLinkStatus.COMPLETED:
        link.status = ChildLinkStatus.COMPLETED
        link.save(update_fields=["status", "updated_at"])
        WorkflowRunEvent.objects.create(
            run=link.parent_run,
            sequence=_next_sequence(link.parent_run),
            event_type="child_completed",
            node_id=link.call_site,
            outcome="completed",
        )
    return {"output": output}


def cancel_children(parent_run: WorkflowRun) -> None:
    """Propagate parent cancellation to pending children (bounded, idempotent)."""
    links = (
        WorkflowChildLink.objects.select_for_update()
        .filter(parent_run=parent_run)
        .exclude(status__in=CHILD_LINK_TERMINAL_STATUSES)
    )
    for link in links:
        _cancel_child_run(link)
        link.status = ChildLinkStatus.CANCELLED
        link.reason_code = "parent_cancelled"
        link.save(update_fields=["status", "reason_code", "updated_at"])


# --------------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------------
def _verified_parent_payload(parent_run: WorkflowRun) -> dict[str, Any]:
    try:
        return verify_execution_context(parent_run.execution_context)
    except ExecutionContextInvalid:
        raise CompositionError("EXECUTION_CONTEXT_INVALID") from None


def _parent_claim(payload: dict[str, Any], parent_run: WorkflowRun) -> dict[str, Any]:
    claim = payload.get("composition")
    if isinstance(claim, dict):
        return claim
    # Top-level parent: seed the tree with the parent's own scenario as the only ancestor.
    return {
        "depth": 0,
        "ancestry": [parent_run.scenario_id],
        "calls": 0,
        "root_run": parent_run.id,
    }


def _resolve_active_child(
    parent_run: WorkflowRun, config: dict[str, Any], kind: str
) -> tuple[Any, Any, dict[str, Any]]:
    from apps.catalog.models import LifecycleStatus, Scenario
    from apps.releases.models import ReleaseStatus, ScenarioRelease

    role_name = config["workflow_role"] if kind == "workflow" else config["agent_role"]
    manifest_role = f"child_{kind}.{role_name}"
    entry = get_manifest_role(parent_run.release, manifest_role)
    pin = entry.get("child") if isinstance(entry, dict) else None
    if not isinstance(pin, dict):
        raise CompositionError("COMPOSITION_CHILD_UNPINNED")

    child_scenario = (
        Scenario.objects.select_related("project").filter(pk=int(pin.get("scenario_id", 0))).first()
    )
    if child_scenario is None:
        raise CompositionError("COMPOSITION_CHILD_UNRESOLVED")
    # Same-organization only (ADR-0009). Cross-organization composition is denied.
    if child_scenario.project.organization_id != parent_run.organization_id:
        raise CompositionError("COMPOSITION_CROSS_ORG_DENIED")
    if child_scenario.status != LifecycleStatus.ACTIVE:
        raise CompositionError("COMPOSITION_CHILD_DISABLED")
    child_release = ScenarioRelease.objects.filter(
        scenario=child_scenario, status=ReleaseStatus.ACTIVE
    ).first()
    if child_release is None:
        raise CompositionError("COMPOSITION_CHILD_NO_RELEASE")
    # The runtime never resolves a newer child: the active release must still match the parent pin.
    if child_release.id != pin.get(
        "release_id"
    ) or child_release.artifact_manifest_sha256 != pin.get("release_checksum"):
        raise CompositionError("COMPOSITION_CHILD_STALE")
    return child_scenario, child_release, pin


def _effective_child_capabilities(
    *,
    kind: str,
    node_config: dict[str, Any],
    parent_payload: dict[str, Any],
    consumer: Any,
    child_scenario: Any,
    child_release: Any,
) -> set[str]:
    """Intersection of the four required ADR-0009 sources. Any missing source ⇒ empty ⇒ deny."""
    source_parent = {str(c) for c in parent_payload.get("capabilities", [])}
    source_callsite = _callsite_envelope(kind, node_config)
    source_child_release = _child_release_allowlist(kind, child_release)
    source_live = _live_consumer_authz(consumer, child_scenario)
    return source_parent & source_callsite & source_child_release & source_live


def _callsite_envelope(kind: str, config: dict[str, Any]) -> set[str]:
    if kind == "agent":
        env = {Capability.AGENT_INVOKE.value}
        for action in config.get("allowed_actions", []):
            env |= set(_ACTION_CAPS.get(action, frozenset()))
        return env
    # A sub-workflow may contain any node kind; the broad call-site envelope is narrowed by the
    # child release allowlist and the live consumer authorization.
    return {
        Capability.WORKFLOW_RUN.value,
        Capability.QUERY.value,
        Capability.TOOL_CALL.value,
        Capability.TOOL_CALL_SIDE_EFFECT.value,
        Capability.AGENT_INVOKE.value,
        Capability.RETRIEVE_DEBUG.value,
    }


def _child_release_allowlist(kind: str, child_release: Any) -> set[str]:
    caps: set[str] = {_BASE_CAP[kind]}
    if kind == "workflow":
        from apps.workflows.services import resolve_release_workflow

        wf_version = resolve_release_workflow(child_release)
        types = {n.get("type") for n in wf_version.compiled_graph.get("nodes", [])}
        if types & {"retrieve", "generate"}:
            caps.add(Capability.QUERY.value)
        if "tool" in types:
            caps |= {Capability.TOOL_CALL.value, Capability.TOOL_CALL_SIDE_EFFECT.value}
    else:
        from apps.agents.services import resolve_release_agent

        ag_version = resolve_release_agent(child_release)
        cfg = ag_version.compiled_config
        caps.add(Capability.QUERY.value)  # a respond decision generates over the model provider
        if cfg.get("tools"):
            caps |= {Capability.TOOL_CALL.value, Capability.TOOL_CALL_SIDE_EFFECT.value}
    return caps


def _live_consumer_authz(consumer: Any, child_scenario: Any) -> set[str]:
    from apps.identity.models import BindingStatus, ConsumerBinding

    binding = ConsumerBinding.objects.filter(
        consumer=consumer, scenario=child_scenario, status=BindingStatus.ACTIVE
    ).first()
    if binding is None:
        return set()
    return {str(c) for c in binding.capabilities}


def _issue_child_context(
    *,
    parent_run: WorkflowRun,
    node_id: str,
    child_scenario: Any,
    child_release: Any,
    capabilities: list[str],
    request_id: str,
    composition: dict[str, Any],
) -> dict[str, Any]:
    from apps.gateway.execution_context import issue_execution_context

    return issue_execution_context(
        organization_id=parent_run.organization_id,
        project_id=child_scenario.project_id,
        scenario_id=child_scenario.id,
        scenario_alias=f"composition:{parent_run.id}:{node_id}",
        consumer_id=parent_run.consumer_id,
        capabilities=capabilities,
        release_id=child_release.id,
        request_id=request_id,
        ttl_seconds=CHILD_CONTEXT_TTL_SECONDS,
        composition=composition,
    )


def _create_child_workflow_run(
    *,
    parent_run: WorkflowRun,
    node_id: str,
    child_scenario: Any,
    child_release: Any,
    envelope: dict[str, Any],
    payload_input: dict[str, Any],
    child_context: dict[str, Any],
    deadline: Any,
) -> tuple[WorkflowRun, bool]:
    from apps.workflows.services import _redact, resolve_release_workflow

    version = resolve_release_workflow(child_release)
    idem = f"comp:{parent_run.id}:{node_id}"
    existing = WorkflowRun.objects.filter(
        consumer=parent_run.consumer, idempotency_key=idem
    ).first()
    if existing is not None:
        return existing, False
    run = WorkflowRun(
        organization_id=parent_run.organization_id,
        scenario=child_scenario,
        release=child_release,
        workflow_version=version,
        consumer=parent_run.consumer,
        idempotency_key=idem,
        input_checksum=compute_checksum(payload_input),
        execution_context=child_context,
        redacted_state=_redact(envelope),
        status=WorkflowRunStatus.QUEUED,
        deadline_at=deadline,
    )
    run.full_clean()
    try:
        with transaction.atomic():
            run.save()
    except IntegrityError:
        return WorkflowRun.objects.get(consumer=parent_run.consumer, idempotency_key=idem), False
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=1,
        event_type="run_queued",
        outcome="queued",
        state_checksum=compute_checksum(run.redacted_state),
    )
    return run, True


def _create_child_agent_run(
    *,
    parent_run: WorkflowRun,
    node_id: str,
    child_scenario: Any,
    child_release: Any,
    payload_input: dict[str, Any],
    child_context: dict[str, Any],
    deadline: Any,
) -> tuple[Any, bool]:
    from apps.agents.limits import resolve_limits
    from apps.agents.models import AgentRun, AgentRunEvent, AgentRunStatus
    from apps.agents.services import _redact, resolve_release_agent

    version = resolve_release_agent(child_release)
    limits = resolve_limits(version.compiled_config.get("limits"))
    snapshot = {"input": _redact(payload_input), "limits": limits.as_dict()}
    idem = f"comp:{parent_run.id}:{node_id}"
    existing = AgentRun.objects.filter(consumer=parent_run.consumer, idempotency_key=idem).first()
    if existing is not None:
        return existing, False
    run = AgentRun(
        organization_id=parent_run.organization_id,
        scenario=child_scenario,
        release=child_release,
        agent_version=version,
        consumer=parent_run.consumer,
        idempotency_key=idem,
        input_checksum=compute_checksum(payload_input),
        execution_context=child_context,
        start_snapshot=snapshot,
        checkpoint=dict(snapshot),
        status=AgentRunStatus.QUEUED,
        deadline_at=deadline,
    )
    run.full_clean(exclude=["public_id"])
    try:
        with transaction.atomic():
            run.save()
    except IntegrityError:
        return AgentRun.objects.get(consumer=parent_run.consumer, idempotency_key=idem), False
    AgentRunEvent.objects.create(
        run=run,
        sequence=1,
        event_type="run_queued",
        outcome="queued",
        state_checksum=compute_checksum(snapshot),
    )
    return run, True


def _create_link(
    *,
    parent_run: WorkflowRun,
    node_id: str,
    kind: str,
    child_scenario: Any,
    child_release: Any,
    pin: dict[str, Any],
    child_run: Any,
    effective_checksum: str,
    depth: int,
) -> WorkflowChildLink:
    link = WorkflowChildLink(
        organization_id=parent_run.organization_id,
        parent_run=parent_run,
        call_site=node_id,
        child_kind=kind,
        child_scenario=child_scenario,
        child_release=child_release,
        child_release_checksum=child_release.artifact_manifest_sha256,
        child_artifact_checksum=str(pin.get("artifact_checksum", "")),
        effective_capability_checksum=effective_checksum,
        depth=depth,
        status=ChildLinkStatus.ADMITTED,
    )
    if kind == "workflow":
        link.child_workflow_run = child_run
        link.child_public_ref = str(child_run.id)
    else:
        link.child_agent_run = child_run
        link.child_public_ref = str(child_run.public_id)
    # Uniqueness is enforced by the DB constraint + IntegrityError branch below; skip the ORM
    # uniqueness probe so a concurrent duplicate resolves to the committed winner (not a raise).
    link.full_clean(validate_unique=False)
    try:
        with transaction.atomic():
            link.save()
    except IntegrityError:
        return WorkflowChildLink.objects.get(parent_run=parent_run, call_site=node_id)
    return link


def _dispatch_child(*, kind: str, child_run_id: int, organization_id: int) -> None:
    if kind == "workflow":
        from apps.workflows.tasks import execute_workflow_run

        transaction.on_commit(lambda: execute_workflow_run.delay(child_run_id, organization_id))
    else:
        from apps.agents.tasks import execute_agent_run

        transaction.on_commit(lambda: execute_agent_run.delay(child_run_id, organization_id))


def _cancel_child_run(link: WorkflowChildLink) -> None:
    if link.child_kind == "workflow" and link.child_workflow_run_id:
        wf_run = (
            WorkflowRun.objects.select_for_update().filter(pk=link.child_workflow_run_id).first()
        )
        if wf_run is not None and wf_run.status not in WORKFLOW_TERMINAL_STATUSES:
            wf_run.status = WorkflowRunStatus.CANCELLED
            wf_run.finished_at = timezone.now()
            wf_run.save(update_fields=["status", "finished_at", "updated_at"])
    elif link.child_kind == "agent" and link.child_agent_run_id:
        from apps.agents.models import TERMINAL_RUN_STATUSES, AgentRun, AgentRunStatus

        ag_run = AgentRun.objects.select_for_update().filter(pk=link.child_agent_run_id).first()
        if ag_run is not None and ag_run.status not in TERMINAL_RUN_STATUSES:
            ag_run.status = AgentRunStatus.CANCELLED
            ag_run.finished_at = timezone.now()
            ag_run.save(update_fields=["status", "finished_at", "updated_at"])


def _mark_link_failed(link: WorkflowChildLink, child_status: str) -> None:
    if link.status in CHILD_LINK_TERMINAL_STATUSES:
        return
    link.status = ChildLinkStatus.FAILED
    link.reason_code = _child_fail_code(child_status)
    link.save(update_fields=["status", "reason_code", "updated_at"])
    WorkflowRunEvent.objects.create(
        run=link.parent_run,
        sequence=_next_sequence(link.parent_run),
        event_type="child_failed",
        node_id=link.call_site,
        outcome="failed",
        reason_code=link.reason_code,
    )


def _child_fail_code(child_status: str) -> str:
    if child_status in {WorkflowRunStatus.TIMED_OUT, "timed_out"}:
        return "COMPOSITION_CHILD_TIMED_OUT"
    if child_status in {WorkflowRunStatus.CANCELLED, "cancelled"}:
        return "COMPOSITION_CHILD_CANCELLED"
    return "COMPOSITION_CHILD_FAILED"


def _validate_child_input(child_release: Any, payload_input: dict[str, Any]) -> None:
    _validate_against_contract(
        child_release, "input_contract", payload_input, ("COMPOSITION_CHILD_INPUT_INVALID")
    )


def _validate_child_output(child_release: Any, output: dict[str, Any]) -> None:
    _validate_against_contract(
        child_release, "output_contract", output, ("COMPOSITION_CHILD_OUTPUT_INVALID")
    )


def _validate_against_contract(
    child_release: Any, role: str, value: dict[str, Any], code: str
) -> None:
    import jsonschema

    from apps.releases.services import get_artifact_body_for_role

    schema = get_artifact_body_for_role(child_release, role)
    if schema is None:
        return
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError:
        raise CompositionError(code) from None


def _assert_mapped_size(value: dict[str, Any]) -> None:
    size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > MAX_MAPPED_BYTES:
        raise CompositionError("COMPOSITION_MAPPED_TOO_LARGE")


def _assert_cumulative_tokens(link: WorkflowChildLink) -> None:
    total = 0
    for other in (
        WorkflowChildLink.objects.filter(parent_run_id=link.parent_run_id)
        .exclude(child_agent_run__isnull=True)
        .select_related("child_agent_run")
    ):
        agent_run = other.child_agent_run
        if agent_run is not None:
            total += int(agent_run.input_tokens) + int(agent_run.output_tokens)
    if total > MAX_COMPOSITION_TOKENS:
        raise CompositionError("COMPOSITION_MAX_TOKENS")


def _next_sequence(run: WorkflowRun) -> int:
    from apps.workflows.services import _next_sequence as next_sequence

    return next_sequence(run)
