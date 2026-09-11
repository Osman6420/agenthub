import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Scenario
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import OrganizationMembership
from apps.tools.approvals import ToolApprovalError, decide_approval, request_tool_invocation
from apps.tools.models import ApprovalRequest, ApprovalStatus
from apps.tools.tests.test_approvals import CAPS, _setup

pytestmark = pytest.mark.django_db


def _approver(release, username: str):
    user = get_user_model().objects.create_user(username=username)
    membership = OrganizationMembership.objects.create(
        organization=release.scenario.organization,
        user=user,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=release.scenario.organization,
        scenario=release.scenario,
        membership=membership,
        responsibility=ScenarioResponsibility.APPROVER,
        assigned_by=user,
    )
    return user


def _pending(release, consumer, *, initiated_by_user=None):
    invocation = request_tool_invocation(
        release=release,
        consumer=consumer,
        role="tool_binding.search",
        tool_input={"query": "hi"},
        idempotency_key="scenario-approval",
        consumer_capabilities=CAPS,
        initiated_by_user=initiated_by_user,
    )
    return ApprovalRequest.objects.get(invocation=invocation)


def test_consumer_subject_matching_username_is_not_human_self_approval() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    consumer.subject = "approver-name"
    consumer.save(update_fields=["subject", "updated_at"])
    actor = _approver(release, "approver-name")
    approval = _pending(release, consumer)

    decided = decide_approval(
        approval_id=approval.pk,
        organization_id=approval.organization_id,
        actor=actor,
        approve=True,
    )

    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by_user == actor


def test_verified_human_initiator_cannot_decide_same_request() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    actor = _approver(release, "human-initiator")
    approval = _pending(release, consumer, initiated_by_user=actor)

    with pytest.raises(ToolApprovalError, match="SELF_APPROVAL_FORBIDDEN"):
        decide_approval(
            approval_id=approval.pk,
            organization_id=approval.organization_id,
            actor=actor,
            approve=True,
        )


def test_approver_responsibility_does_not_cross_scenarios() -> None:
    release, consumer = _setup(risk="high", side_effecting=True, required=True)
    actor = get_user_model().objects.create_user(username="other-scenario-approver")
    membership = OrganizationMembership.objects.create(
        organization=release.scenario.organization,
        user=actor,
    )
    sibling = Scenario.objects.create(
        organization=release.scenario.organization,
        project=release.scenario.project,
        slug="other",
        name="Other",
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=release.scenario.organization,
        scenario=sibling,
        membership=membership,
        responsibility=ScenarioResponsibility.APPROVER,
        assigned_by=actor,
    )
    approval = _pending(release, consumer)

    with pytest.raises(ToolApprovalError, match="APPROVER_NOT_AUTHORIZED"):
        decide_approval(
            approval_id=approval.pk,
            organization_id=approval.organization_id,
            actor=actor,
            approve=True,
        )
