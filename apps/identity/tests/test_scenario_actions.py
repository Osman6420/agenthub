"""Permission presentation stays equal to live policy and independent of readiness."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.identity.authorization import Capability, authorize
from apps.identity.models import ScenarioResponsibility, ScenarioResponsibilityAssignment
from apps.identity.scenario_actions import authorize_scenario_action, scenario_allowed_actions
from apps.identity.tests.test_responsibility_authorization import _member, _scope

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role", ScenarioResponsibility.values)
def test_actions_match_exact_policy_without_readiness_or_other_scope_fallback(role):
    org, project, scenario, sibling, _ = _scope("actions")
    user, membership = _member(org, "actions-user")
    assignment = ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        scenario=scenario,
        membership=membership,
        responsibility=role,
        assigned_by=user,
    )
    actions = scenario_allowed_actions(user=user, scenario=scenario)
    assert actions["compile"] == (
        role
        in {
            ScenarioResponsibility.EDITOR,
            ScenarioResponsibility.MANAGER,
            ScenarioResponsibility.RELEASE_MANAGER,
        }
    )
    assert actions["release"] == (
        role in {ScenarioResponsibility.MANAGER, ScenarioResponsibility.RELEASE_MANAGER}
    )
    assert (
        actions["edit"]
        == authorize(user=user, scenario=scenario, capability=Capability.SCENARIO_EDIT).allowed
    )
    assert actions["approve"] == (role == ScenarioResponsibility.APPROVER)
    assert not any(scenario_allowed_actions(user=user, scenario=sibling).values())
    assert not authorize_scenario_action(user=user, scenario=scenario, action="unlisted").allowed
    # No draft, index or active release is needed to hold an action permission.
    assert scenario.status != "active"
    assignment.expires_at = timezone.now() - timedelta(seconds=1)
    assignment.save()
    assert not any(scenario_allowed_actions(user=user, scenario=scenario).values())
