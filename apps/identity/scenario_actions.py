"""Closed, presentation-neutral scenario actions derived only from operator policy.

These are permissions, not readiness. Each mutation must resolve a trusted target
and re-evaluate the action; a browser's copy is never accepted as authorization.
"""

from typing import Any

from apps.catalog.models import Scenario
from apps.identity.authorization import (
    AuthoritySource,
    AuthorizationDecision,
    Capability,
    authorize,
)

SCENARIO_ACTION_CAPABILITIES: dict[str, tuple[Capability, ...]] = {
    "view": (Capability.SCENARIO_VIEW,),
    "edit": (Capability.SCENARIO_EDIT,),
    "compile": (Capability.SCENARIO_EDIT, Capability.SCENARIO_RELEASE),
    "test": (Capability.SCENARIO_TEST,),
    "release": (Capability.SCENARIO_RELEASE,),
    "access": (Capability.SCENARIO_ACCESS_MANAGE,),
    "runtime_view": (Capability.RUNTIME_VIEW,),
    "runtime_cancel": (Capability.RUNTIME_CANCEL,),
    "runtime_pause": (Capability.RUNTIME_PAUSE,),
    "runtime_resume": (Capability.RUNTIME_RESUME,),
    "approve": (Capability.SCENARIO_APPROVAL_DECIDE,),
}


def authorize_scenario_action(
    *, user: Any, scenario: Scenario, action: str
) -> AuthorizationDecision:
    decision = AuthorizationDecision(False, AuthoritySource.NONE, "UNKNOWN_SCENARIO_ACTION")
    for capability in SCENARIO_ACTION_CAPABILITIES.get(action, ()):
        decision = authorize(user=user, scenario=scenario, capability=capability)
        if decision.allowed:
            return decision
    return decision


def scenario_allowed_actions(*, user: Any, scenario: Scenario) -> dict[str, bool]:
    # Reuse identical capability decisions within this one response, never across
    # requests or mutations. In particular, compile must not imply publication.
    capabilities = dict.fromkeys(
        capability for group in SCENARIO_ACTION_CAPABILITIES.values() for capability in group
    )
    decisions = {
        capability: authorize(user=user, scenario=scenario, capability=capability).allowed
        for capability in capabilities
    }
    return {
        action: any(decisions[capability] for capability in capabilities)
        for action, capabilities in SCENARIO_ACTION_CAPABILITIES.items()
    }
