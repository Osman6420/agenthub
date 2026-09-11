"""Commit a bounded active-generation choice before performing retrieval I/O.

This service owns a durable transaction. Callers must invoke it outside their
node transaction; nesting it would allow a later worker failure to erase the
choice and silently change the data used by a retry.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.documents.retrieve_scope import live_consumer_scenario_grants
from apps.releases.execution import release_revision, run_workflow_graph
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import (
    Run,
    RunBranch,
    RunRetrievalGeneration,
    RunRetrievalSelection,
)

MAX_SELECTIONS_PER_RUN = 2048
MAX_GENERATIONS_PER_SELECTION = 200


class RetrievalSelectionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RetrievalSelection:
    id: int
    document_set_version_ids: tuple[int, ...]
    index_version_ids: tuple[int, ...]


def _result(selection: RunRetrievalSelection) -> RetrievalSelection:
    pairs = list(
        selection.generations.order_by("document_set_id").values_list(
            "document_set_version_id", "index_version_id"
        )[: MAX_GENERATIONS_PER_SELECTION + 1]
    )
    if len(pairs) != selection.generation_count:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_INCOMPLETE")
    return RetrievalSelection(selection.pk, tuple(p[0] for p in pairs), tuple(p[1] for p in pairs))


def _assert_owner(run: Run, owner_token: UUID, branch_id: UUID | None) -> None:
    now = timezone.now()
    if run.cancellation_state != "none" or run.deadline_at <= now:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_RUN_UNAVAILABLE")
    if branch_id is not None:
        if (
            run.status != "waiting_child"
            or not RunBranch.objects.filter(
                pk=branch_id,
                run=run,
                organization_id=run.organization_id,
                status="running",
                delivery_token=owner_token,
                claim_expires_at__gt=now,
            ).exists()
        ):
            raise RetrievalSelectionError("RETRIEVAL_SELECTION_OWNER_INVALID")
    elif run.status != "running" or not (
        (
            run.execution_mode == "background"
            and run.background_claim_token == owner_token
            and run.background_claim_checkpoint_version == run.checkpoint_version
            and run.background_claim_expires_at is not None
            and run.background_claim_expires_at > now
        )
        or (
            run.execution_mode == "sync"
            and run.sync_lease_token == owner_token
            and run.sync_lease_expires_at is not None
            and run.sync_lease_expires_at > now
        )
    ):
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_OWNER_INVALID")


def read_active_selection(
    *,
    organization_id: int,
    run_id: UUID,
    release_id: int,
    consumer_id: int,
    selection_id: int,
    query: str,
    profile: dict[str, Any],
) -> RetrievalSelection:
    """Resolve an exact receipt for the current run; this does not grant data access."""
    selection = RunRetrievalSelection.objects.filter(
        pk=selection_id,
        organization_id=organization_id,
        run_id=run_id,
        run__organization_id=organization_id,
        run__consumer_id=consumer_id,
        run__release_id=release_id,
        revision__source_release_id=release_id,
        revision__organization_id=organization_id,
        revision_id=F("run__scenario_revision_id"),
    ).first()
    if selection is None:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_UNRESOLVED")
    if selection.criteria_checksum != compute_checksum({"query": query, "profile": profile}):
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_REPLAY_CONFLICT")
    return _result(selection)


@transaction.atomic(durable=True)
def capture_active_selection(
    *,
    organization_id: int,
    run_id: UUID,
    owner_token: UUID,
    node_id: str,
    query: str,
    profile: dict[str, Any],
    branch_id: UUID | None = None,
    agent_step: int | None = None,
) -> RetrievalSelection:
    """Select active generations once under the exact worker's current claim."""
    if (
        not isinstance(owner_token, UUID)
        or not isinstance(run_id, UUID)
        or (branch_id is not None and not isinstance(branch_id, UUID))
        or not isinstance(node_id, str)
        or not 1 <= len(node_id) <= 100
        or (
            agent_step is not None
            and (
                isinstance(agent_step, bool)
                or not isinstance(agent_step, int)
                or not 0 <= agent_step < 1000
            )
        )
        or not isinstance(query, str)
        or not isinstance(profile, dict)
    ):
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_INPUT_INVALID")
    criteria = {"query": query, "profile": profile}
    try:
        encoded = json.dumps(criteria, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_INPUT_INVALID") from None
    if len(encoded) > 65536:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_INPUT_TOO_LARGE")
    checksum = compute_checksum(criteria)
    set_tenant_context(organization_id)
    run = (
        Run.objects.select_for_update(of=("self",))
        .select_related("release", "consumer", "workflow_version")
        .filter(pk=run_id, organization_id=organization_id)
        .first()
    )
    if run is None:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_RUN_UNRESOLVED")
    _assert_owner(run, owner_token, branch_id)
    graph = run_workflow_graph(run)
    node = next((n for n in graph["nodes"] if n["id"] == node_id), None)
    if node is None or node["type"] != ("retrieve" if agent_step is None else "agent_loop"):
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_NODE_INVALID")
    revision, snapshot = release_revision(run.release)
    if revision is None or snapshot is None or snapshot["data"]["selection"] != "active_generation":
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_MODE_INVALID")
    key = f"node:{node_id}"
    if branch_id is not None:
        key = f"branch:{branch_id}:{key}"
    if agent_step is not None:
        key += f":agent:{agent_step}"
    previous = RunRetrievalSelection.objects.filter(run=run, step_key=key).first()
    if previous is not None:
        if previous.criteria_checksum != checksum or previous.revision_id != revision.pk:
            raise RetrievalSelectionError("RETRIEVAL_SELECTION_REPLAY_CONFLICT")
        return _result(previous)
    if run.retrieval_selections.count() >= MAX_SELECTIONS_PER_RUN:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_LIMIT")
    allowed = live_consumer_scenario_grants(consumer=run.consumer, scenario_ids=[run.scenario_id])
    set_ids = list(
        allowed.filter(document_set_id__in=snapshot["data"]["document_set_ids"])
        .order_by("document_set_id")
        .values_list("document_set_id", flat=True)
    )
    # Match promotion's set -> version -> index order. Lock sets even when no
    # active version exists, so a half-ready generation cannot enter the receipt.
    locked_ids = list(
        DocumentSet.objects.select_for_update()
        .filter(pk__in=set_ids, organization_id=organization_id)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if len(locked_ids) > MAX_GENERATIONS_PER_SELECTION:
        raise RetrievalSelectionError("RETRIEVAL_SELECTION_LIMIT")
    versions = list(
        DocumentSetVersion.objects.filter(
            document_set_id__in=locked_ids, organization_id=organization_id, status="active"
        )
        .select_related("built_index_version")
        .order_by("document_set_id")
    )
    prepared_indexes = {}
    if run.prepared_evaluation_id is not None:
        from apps.evaluations.prepared import prepared_run_generations

        pins = prepared_run_generations(run)
        versions = [p.document_set_version for p in pins]
        prepared_indexes = {p.document_set_version_id: p.index_version for p in pins}
    if len(versions) != len(locked_ids):
        raise RetrievalSelectionError("RETRIEVAL_GENERATION_NOT_READY")
    indexes = {}
    for version in versions:
        index = prepared_indexes.get(version.pk) or version.built_index_version
        if (
            index is None
            or index.organization_id != organization_id
            or index.document_set_version_id != version.pk
            or (
                index.status != "active"
                if run.prepared_evaluation_id is None
                else index.status not in {"promotable", "active", "superseded"}
            )
            or not index.store_ready
            or (index.storage_layout == "shared_v1" and index.storage_state != "sealed")
        ):
            raise RetrievalSelectionError("RETRIEVAL_GENERATION_NOT_READY")
        indexes[version.pk] = index
    selection = RunRetrievalSelection.objects.create(
        organization_id=organization_id,
        run=run,
        revision=revision,
        step_key=key,
        criteria_checksum=checksum,
        generation_count=len(versions),
    )
    RunRetrievalGeneration.objects.bulk_create(
        [
            RunRetrievalGeneration(
                organization_id=organization_id,
                selection=selection,
                document_set_id=version.document_set_id,
                document_set_version=version,
                index_version=indexes[version.pk],
            )
            for version in versions
        ],
        batch_size=100,
    )
    record_event(
        actor_type="system",
        actor_id="workflow-runtime",
        action="run.retrieval.selected",
        outcome="success",
        organization_id=organization_id,
        resource_type="run",
        resource_id=str(run.pk),
        reason="ACTIVE_GENERATION_PINNED",
        after={"selection_id": selection.pk, "generation_count": len(versions)},
    )
    return _result(selection)
