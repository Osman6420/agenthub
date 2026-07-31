import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.catalog.models import AIProject, Scenario
from apps.console.context import SESSION_KEY
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


def test_membership_is_roleless_and_assignment_uses_member_dropdown(client) -> None:
    organization = Organization.objects.create(slug="access-ui", name="Access UI")
    administrator = get_user_model().objects.create_user(username="administrator")
    target = get_user_model().objects.create_user(username="target-user")
    admin_membership = OrganizationMembership.objects.create(
        organization=organization,
        user=administrator,
    )
    target_membership = OrganizationMembership.objects.create(
        organization=organization,
        user=target,
    )
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=administrator,
    )
    project = AIProject.objects.create(
        organization=organization,
        slug="project",
        name="Project",
    )
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="scenario",
        name="Scenario",
    )
    client.force_login(administrator)
    session = client.session
    session[SESSION_KEY] = organization.pk
    session.save()

    response = client.get(reverse("console:organization_members"))

    assert response.status_code == 200
    assert b'<select name="user"' in response.content
    assert b'name="member"' in response.content
    assert b"target-user" in response.content
    assert b'name="role"' not in response.content

    response = client.post(
        reverse("console:delegated_assignment_add"),
        {
            "responsibility": ScenarioResponsibility.APPROVER,
            "member": target_membership.pk,
            "scenario": scenario.pk,
        },
    )

    assert response.status_code == 302
    assert ScenarioResponsibilityAssignment.objects.filter(
        scenario=scenario,
        membership=target_membership,
        responsibility=ScenarioResponsibility.APPROVER,
    ).exists()
