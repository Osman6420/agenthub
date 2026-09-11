"""Reviewed, resumable publication with a single atomic live transition."""

import re
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.builder.models import ArtifactDraft, WorkflowDraft
from apps.builder.services import _prepare_verified_candidate
from apps.catalog.lifecycle import _assert_release_indexes_served, activate_scenario
from apps.catalog.models import Scenario, ScenarioAlias, ScenarioDataSelection
from apps.documents.models import ScenarioDocumentSetBinding
from apps.evaluations.models import EvalStatus
from apps.evaluations.services import _admit_eval, resume_eval
from apps.identity.scenario_actions import authorize_scenario_action
from apps.releases.compiler import workflow_manifest_requirements
from apps.releases.lifecycle import promote
from apps.releases.models import ScenarioPublication, ScenarioRelease
from apps.releases.scenario_artifacts import SCENARIO_SCOPED_ROLES, scenario_artifact_logical_id
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.workflows.compiler import compile_workflow
from apps.workflows.models import CustomNodeDefinition


class PublicationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _bounded(rows, limit: int = 200):
    values = list(rows[: limit + 1])
    if len(values) > limit:
        raise PublicationError("PUBLICATION_SCOPE_TOO_LARGE")
    return values


def _workflow(scenario: Scenario, *, lock: bool = False) -> WorkflowDraft:
    query = WorkflowDraft.objects.filter(
        scenario=scenario, organization_id=scenario.organization_id, project_id=scenario.project_id
    )
    if lock:
        query = query.select_for_update()
    drafts = list(query.order_by("pk")[:2])
    if len(drafts) != 1:
        raise PublicationError("PUBLICATION_SINGLE_WORKFLOW_REQUIRED")
    return drafts[0]


def publication_token(scenario: Scenario, *, lock: bool = False) -> str:
    """Checksum only the current authored inputs and serving baseline; no secret values."""
    draft = _workflow(scenario, lock=lock)
    custom_nodes = _bounded(
        CustomNodeDefinition.objects.filter(
            organization_id=scenario.organization_id, status="active"
        )
        .order_by("pk")
        .values_list("logical_id", "version"),
        1000,
    )
    compiled = compile_workflow(
        draft.body,
        allowed_custom_nodes=frozenset(f"{name}.v{version}" for name, version in custom_nodes),
    )
    requirements = workflow_manifest_requirements(compiled.graph)
    if len(requirements) > 50:
        raise PublicationError("PUBLICATION_SCOPE_TOO_LARGE")
    wanted = {
        (str(item["artifact_type"]), str(role).removeprefix("child_workflow."))
        for role, item in requirements.items()
        if role != "workflow_definition"
    }
    wanted.update(
        (str(kind), scenario_artifact_logical_id(scenario, kind)) for kind in SCENARIO_SCOPED_ROLES
    )
    pins = []
    for kind, logical_id in sorted(wanted):
        pin = (
            ArtifactVersion.objects.filter(
                organization_id=scenario.organization_id, type=kind, logical_id=logical_id
            )
            .order_by("-version")
            .values_list("pk", "checksum")
            .first()
        )
        pins.append([kind, logical_id, pin])
    artifacts = ArtifactDraft.objects.filter(
        organization_id=scenario.organization_id, scenario=scenario
    ).order_by("pk")
    if lock:
        artifacts = artifacts.select_for_update()
    authored = _bounded(artifacts.values_list("pk", "revision"))
    baseline = (
        ScenarioRelease.objects.filter(scenario=scenario, status="active")
        .values_list("pk", "artifact_manifest_sha256")
        .first()
    )
    bindings = _bounded(
        ScenarioDocumentSetBinding.objects.filter(
            scenario=scenario, organization_id=scenario.organization_id
        )
        .order_by("pk")
        .values_list("pk", "document_set_id")
    )
    # In legacy mode a new published data version changes the release being reviewed.
    # Active-generation mode deliberately chooses its data at run admission instead.
    data_versions = []
    if scenario.data_selection == ScenarioDataSelection.LEGACY_PINNED:
        from apps.documents.services import pinned_document_set_version_ids

        data_versions = pinned_document_set_version_ids(scenario)
    children = []
    if any(str(role).startswith("child_workflow.") for role in requirements):
        # Only composition workflows depend on other currently live releases. Keep this
        # review bounded; the canonical compiler remains the authority for exact pins.
        children = _bounded(
            ScenarioRelease.objects.filter(
                organization_id=scenario.organization_id, status="active"
            )
            .exclude(scenario=scenario)
            .order_by("pk")
            .values_list("pk", "artifact_manifest_sha256")
        )
    return compute_checksum(
        {
            "contract": "scenario-publication-review/v1",
            "scenario": scenario.pk,
            "execution": scenario.execution_contract,
            "selection": scenario.data_selection,
            "status": scenario.status,
            "draft": [draft.pk, draft.revision, compute_checksum(draft.body)],
            "authored": authored,
            "pins": pins,
            "baseline": baseline,
            "bindings": bindings,
            "data_versions": data_versions,
            "children": children,
            "custom_nodes": custom_nodes,
        }
    )


def _authorize(actor: Any, scenario: Scenario) -> tuple[Any, Scenario]:
    set_tenant_context(scenario.organization_id)
    Organization.objects.select_for_update(no_key=True).get(pk=scenario.organization_id)
    current = (
        Scenario.objects.select_for_update(no_key=True)
        .select_related("organization", "project")
        .filter(
            pk=scenario.pk,
            organization_id=scenario.organization_id,
            project__organization_id=scenario.organization_id,
        )
        .first()
    )
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is None:
        raise PermissionDenied
    actor = get_user_model().objects.filter(pk=actor_pk, is_active=True).first()
    if (
        actor is None
        or current is None
        or not all(
            authorize_scenario_action(user=actor, scenario=current, action=action).allowed
            for action in ("compile", "test", "release")
        )
    ):
        raise PermissionDenied
    return actor, current


def _audit(publication, actor, action, *, outcome="success", reason="", request_id=""):
    record_event(
        actor_type="user",
        actor_id=str(actor.pk),
        organization_id=publication.organization_id,
        action=f"scenario.publication.{action}",
        outcome=outcome,
        reason=reason,
        resource_type="scenario_publication",
        resource_id=str(publication.public_id),
        request_id=request_id,
        after={"release_id": publication.release_id, "evaluation_id": publication.evaluation_id},
    )


@transaction.atomic
def _prepare(*, actor, scenario, intent, expected, request_id):
    actor, scenario = _authorize(actor, scenario)
    existing = (
        ScenarioPublication.objects.select_related("release", "evaluation")
        .filter(
            public_id=intent,
            organization_id=scenario.organization_id,
            scenario=scenario,
        )
        .first()
    )
    if existing is not None:
        if existing.source_job_id is not None:
            raise PublicationError("PUBLICATION_ORIGIN_MISMATCH")
        if existing.created_by != str(actor.pk):
            raise PermissionDenied
        if existing.request_checksum != expected:
            raise PublicationError("PUBLICATION_INTENT_CONFLICT")
        if existing.completed_at is None and existing.prepared_checksum != publication_token(
            scenario, lock=True
        ):
            raise PublicationError("PUBLICATION_SETTINGS_CHANGED")
        return existing
    if expected != publication_token(scenario, lock=True):
        raise PublicationError("PUBLICATION_SETTINGS_CHANGED")
    if not ScenarioAlias.objects.filter(scenario=scenario, status="active").exists():
        raise PublicationError("ACTIVE_ALIAS_REQUIRED")
    baseline = ScenarioRelease.objects.filter(scenario=scenario, status="active").first()
    draft = _workflow(scenario, lock=True)
    prepared = _prepare_verified_candidate(
        draft,
        actor=actor.get_username(),
        expected_revision=draft.revision,
        version_description="Senaryo sayfasından yayına alındı",
        request_id=request_id,
    )
    if prepared.release is None:
        raise PublicationError("PUBLICATION_CONFIGURATION_INCOMPLETE")
    evaluation, _ = _admit_eval(release=prepared.release, created_by=actor.get_username())
    publication = ScenarioPublication.objects.create(
        public_id=intent,
        organization_id=scenario.organization_id,
        scenario=scenario,
        draft=draft,
        baseline_release=baseline,
        release=prepared.release,
        evaluation=evaluation,
        request_checksum=expected,
        prepared_checksum=publication_token(scenario, lock=True),
        created_by=str(actor.pk),
    )
    _audit(publication, actor, "prepared", request_id=request_id)
    return publication


@transaction.atomic
def _finish(*, publication, actor, scenario, request_id):
    actor, scenario = _authorize(actor, scenario)
    publication = (
        ScenarioPublication.objects.select_for_update(of=("self",))
        .select_related("release", "evaluation")
        .get(pk=publication.pk, scenario=scenario, organization_id=scenario.organization_id)
    )
    if publication.created_by != str(actor.pk):
        raise PermissionDenied
    if publication.completed_at is not None:
        return publication
    if publication.prepared_checksum != publication_token(scenario, lock=True):
        raise PublicationError("PUBLICATION_SETTINGS_CHANGED")
    evaluation = publication.evaluation
    if (
        evaluation.status != EvalStatus.PASSED
        or evaluation.total_cases < 1
        or evaluation.passed_cases != evaluation.total_cases
        or evaluation.case_results.filter(passed=True).count() != evaluation.total_cases
    ):
        raise PublicationError("PUBLICATION_EVALUATION_NOT_PASSED")
    if (
        not ScenarioAlias.objects.select_for_update()
        .filter(scenario=scenario, status="active")
        .exists()
    ):
        raise PublicationError("ACTIVE_ALIAS_REQUIRED")
    release = promote(release=publication.release, actor=actor.get_username())
    _assert_release_indexes_served(release)
    activate_scenario(scenario, actor=actor, request_id=request_id)
    publication.completed_at = timezone.now()
    publication.save(update_fields=["completed_at"])
    _audit(publication, actor, "completed", request_id=request_id)
    return publication


def publish_scenario(
    *, actor: Any, scenario: Scenario, intent: UUID, expected: str, request_id: str = ""
) -> ScenarioPublication:
    """Commit exact intent, execute outside a transaction, atomically replace the live release."""
    if (
        not isinstance(intent, UUID)
        or not isinstance(expected, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
    ):
        raise PublicationError("PUBLICATION_REQUEST_INVALID")
    publication = None
    try:
        publication = _prepare(
            actor=actor, scenario=scenario, intent=intent, expected=expected, request_id=request_id
        )
        if publication.completed_at is not None:
            return publication
        resume_eval(
            eval_run_id=publication.evaluation_id, organization_id=publication.organization_id
        )
        return _finish(
            publication=publication, actor=actor, scenario=scenario, request_id=request_id
        )
    except Exception as exc:
        with transaction.atomic():
            set_tenant_context(scenario.organization_id)
            code = getattr(exc, "code", "PUBLICATION_FAILED")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", code):
                code = "PUBLICATION_FAILED"
            if isinstance(exc, PermissionDenied):
                code = "PUBLICATION_FORBIDDEN"
            record_event(
                actor_type="user",
                actor_id=str(getattr(actor, "pk", "")),
                organization_id=scenario.organization_id,
                action="scenario.publication.blocked",
                outcome="deny",
                reason=code,
                resource_type="scenario",
                resource_id=str(scenario.pk),
                request_id=request_id,
            )
        raise
