"""Identifier-only Celery delivery for unified Runs and parallel branches."""

from __future__ import annotations

import uuid
from functools import partial

from celery import shared_task
from django.db import transaction

from apps.tenancy.context import set_tenant_context
from apps.workflows.models import Run
from apps.workflows.runtime import WorkflowRuntimeError


def dispatch_unified_run_branches(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    region_node_id: str,
) -> int:
    """Reserve and publish only the branch slots the region may currently run."""

    from apps.workflows.run_parallel import admit_run_branch_deliveries

    deliveries = admit_run_branch_deliveries(
        organization_id=organization_id,
        run_id=run_id,
        region_node_id=region_node_id,
    )
    for delivery in deliveries:
        transaction.on_commit(
            partial(
                execute_unified_run_branch.apply_async,
                args=(str(delivery.branch_id), organization_id, str(delivery.delivery_token)),
                queue="runtime",
            )
        )
    return len(deliveries)


@shared_task(queue="runtime", acks_late=True, reject_on_worker_lost=True)
def execute_unified_run_branch(branch_id: str, organization_id: int, delivery_token: str) -> str:
    """Execute one server-owned unified branch, then converge its join and parent Run."""

    from apps.workflows.models import RunBranch
    from apps.workflows.run_parallel import (
        RunParallelError,
        claim_run_branch,
        complete_run_branch,
    )
    from apps.workflows.run_waits import RunWaitError, resume_run_for_join
    from apps.workflows.unified_executor import (
        UnifiedExecutorError,
        execute_run_branch_path,
    )

    try:
        identifier = uuid.UUID(branch_id)
        token = uuid.UUID(delivery_token)
    except (AttributeError, TypeError, ValueError):
        return "invalid"
    try:
        claim = claim_run_branch(
            organization_id=organization_id,
            branch_id=identifier,
            delivery_token=token,
        )
        if claim == "claimed":
            with transaction.atomic():
                set_tenant_context(organization_id)
                branch = RunBranch.objects.select_related(
                    "run__workflow_version", "run__release", "run__consumer"
                ).get(pk=identifier, organization_id=organization_id)
                attempt = branch.attempt_count
            try:
                result = execute_run_branch_path(branch=branch, delivery_token=token)
                reason_code = ""
            except (UnifiedExecutorError, WorkflowRuntimeError) as exc:
                result, reason_code = None, exc.code
            claim = complete_run_branch(
                organization_id=organization_id,
                branch_id=identifier,
                delivery_token=token,
                idempotency_key=f"run-branch:{identifier}:attempt:{attempt}",
                result_state=result,
                reason_code=reason_code,
            ).outcome
        branch_location = (
            RunBranch.objects.filter(pk=identifier, organization_id=organization_id)
            .values_list("region_node_id", "run_id")
            .first()
        )
        if branch_location is None:
            return "missing"
        region_node_id, run_id = branch_location
    except (RunBranch.DoesNotExist, Run.DoesNotExist, TypeError):
        return "missing"
    except RunParallelError as exc:
        return f"denied:{exc.code}"
    if claim == "committed":
        try:
            dispatch_unified_run_branches(
                organization_id=organization_id,
                run_id=run_id,
                region_node_id=region_node_id,
            )
        except RunParallelError:
            pass
    try:
        resume_run_for_join(
            organization_id=organization_id,
            run_id=run_id,
            region_node_id=region_node_id,
        )
    except (RunWaitError, Run.DoesNotExist):
        return claim
    try:
        dispatch_unified_background_run(run_id=run_id, organization_id=organization_id)
    except UnifiedExecutorError:
        pass
    return claim


@shared_task(queue="runtime", acks_late=True)
def reconcile_unified_run_branches(limit: int = 100) -> int:
    """Repair expired branch delivery/claim leases and publish safe replacements."""

    from apps.tenancy.models import Organization, OrganizationStatus
    from apps.workflows.run_parallel import RunParallelError, reconcile_run_parallel_work
    from apps.workflows.run_waits import RunWaitError, resume_run_for_join
    from apps.workflows.unified_executor import UnifiedExecutorError

    if not 1 <= limit <= 100:
        return 0
    remaining = limit
    published = 0
    organization_ids = list(
        Organization.objects.filter(status=OrganizationStatus.ACTIVE)
        .order_by("id")
        .values_list("id", flat=True)[:limit]
    )
    for organization_id in organization_ids:
        if remaining <= 0:
            break
        try:
            reconciliation = reconcile_run_parallel_work(
                organization_id=organization_id,
                limit=remaining,
            )
        except RunParallelError:
            continue
        for delivery in reconciliation.deliveries:
            transaction.on_commit(
                partial(
                    execute_unified_run_branch.apply_async,
                    args=(
                        str(delivery.branch_id),
                        organization_id,
                        str(delivery.delivery_token),
                    ),
                    queue="runtime",
                )
            )
        published += len(reconciliation.deliveries)
        remaining -= reconciliation.regions_scanned
        for run_id, region_node_id in reconciliation.closed_regions:
            try:
                resumed = resume_run_for_join(
                    organization_id=organization_id,
                    run_id=run_id,
                    region_node_id=region_node_id,
                )
            except (RunWaitError, Run.DoesNotExist):
                continue
            if resumed.outcome == "committed":
                try:
                    dispatch_unified_background_run(
                        run_id=run_id,
                        organization_id=organization_id,
                    )
                except UnifiedExecutorError:
                    pass
    return published


def dispatch_unified_background_run(
    *,
    run_id: uuid.UUID,
    organization_id: int,
    delivery_token: uuid.UUID | None = None,
) -> uuid.UUID:
    """Schedule an identifier-only unified delivery after the caller commits."""

    from apps.workflows.unified_executor import service_revision

    token = delivery_token or uuid.uuid4()
    transaction.on_commit(
        partial(
            execute_unified_background_run.apply_async,
            args=(str(run_id), str(token)),
            headers={
                "organization_id": organization_id,
                "service_revision": service_revision(),
            },
            queue="runtime",
        )
    )
    return token


@shared_task(
    bind=True,
    queue="runtime",
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_unified_background_run(
    self: object,
    run_id: str,
    delivery_token: str,
) -> str:
    """Run one closed identifier-only delivery through the unified executor."""

    from apps.workflows.background_claims import BackgroundClaimError
    from apps.workflows.unified_executor import (
        UnifiedExecutorError,
        execute_background_delivery,
    )

    headers = getattr(getattr(self, "request", None), "headers", None) or {}
    try:
        return execute_background_delivery(
            body={"run_id": run_id, "delivery_token": delivery_token},
            headers=dict(headers),
        )
    except (BackgroundClaimError, UnifiedExecutorError) as exc:
        return f"denied:{exc.code}"
    except Run.DoesNotExist:
        return "missing"
