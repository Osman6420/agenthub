"""Reviewed opt-in for future publications; existing releases and runs stay immutable."""

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.services import record_event
from apps.catalog.models import ScenarioDataSelection, ScenarioExecutionContract
from apps.documents.models import ScenarioDocumentSetBinding
from apps.identity.scenario_actions import authorize_scenario_action
from apps.releases.models import ScenarioRelease
from apps.releases.publication import PublicationError, _authorize, publication_token
from apps.tenancy.context import set_tenant_context

SALT = "scenario-runtime-transition/v1"


def _authorized(actor, scenario):
    actor, scenario = _authorize(actor, scenario)
    if not authorize_scenario_action(user=actor, scenario=scenario, action="edit").allowed:
        raise PermissionDenied
    return actor, scenario


def _state(scenario):
    current = ScenarioRelease.objects.filter(scenario=scenario, status="active").first()
    if current and current.manifest.get("index_versions"):
        raise PublicationError("RUNTIME_TRANSITION_PINNED_INDEX")
    return {
        "expected": publication_token(scenario, lock=True),
        "current_release": current,
        "document_sets": list(
            ScenarioDocumentSetBinding.objects.filter(
                organization_id=scenario.organization_id, scenario=scenario
            )
            .select_related("document_set")
            .order_by("document_set_id")[:201]
        ),
        "already_enabled": (
            scenario.execution_contract == ScenarioExecutionContract.SNAPSHOT
            and scenario.data_selection == ScenarioDataSelection.ACTIVE_GENERATION
        ),
    }


@transaction.atomic
def preview_runtime_transition(*, actor, scenario):
    actor, scenario = _authorized(actor, scenario)
    state = _state(scenario)
    state["review"] = signing.dumps(
        {"actor": actor.pk, "scenario": scenario.pk, "expected": state["expected"]}, salt=SALT
    )
    return state


def enable_runtime_snapshot(*, actor, scenario, review, request_id=""):
    try:
        with transaction.atomic():
            actor, scenario = _authorized(actor, scenario)
            try:
                reviewed = signing.loads(review, salt=SALT, max_age=3600)
            except (signing.BadSignature, TypeError, ValueError) as exc:
                raise PublicationError("RUNTIME_TRANSITION_REVIEW_EXPIRED") from exc
            if reviewed.get("actor") != actor.pk or reviewed.get("scenario") != scenario.pk:
                raise PublicationError("RUNTIME_TRANSITION_REVIEW_INVALID")
            state = _state(scenario)
            if state["already_enabled"]:
                return scenario
            if reviewed.get("expected") != state["expected"]:
                raise PublicationError("PUBLICATION_SETTINGS_CHANGED")
            before = {
                "execution_contract": scenario.execution_contract,
                "data_selection": scenario.data_selection,
            }
            scenario.execution_contract = ScenarioExecutionContract.SNAPSHOT
            scenario.data_selection = ScenarioDataSelection.ACTIVE_GENERATION
            scenario.save(update_fields=["execution_contract", "data_selection", "updated_at"])
            record_event(
                actor_type="user",
                actor_id=str(actor.pk),
                organization_id=scenario.organization_id,
                action="scenario.runtime.transitioned",
                outcome="success",
                resource_type="scenario",
                resource_id=str(scenario.public_id),
                request_id=request_id,
                before=before,
                after={
                    "execution_contract": scenario.execution_contract,
                    "data_selection": scenario.data_selection,
                },
            )
            return scenario
    except Exception as exc:
        with transaction.atomic():
            set_tenant_context(scenario.organization_id)
            record_event(
                actor_type="user",
                actor_id=str(getattr(actor, "pk", "")),
                organization_id=scenario.organization_id,
                action="scenario.runtime.transition_blocked",
                outcome="deny",
                reason=exc.code if isinstance(exc, PublicationError) else "TRANSITION_DENIED",
                resource_type="scenario",
                resource_id=str(scenario.public_id),
                request_id=request_id,
            )
        raise
