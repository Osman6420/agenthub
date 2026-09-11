import pytest
from django.urls import reverse

from apps.catalog.models import Scenario
from apps.identity.authorization import Capability, authorize
from apps.identity.models import ProjectResponsibility as P
from apps.identity.tests.test_delegated_assignments import _membership
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture
from apps.identity.tests.test_inherited_assignment_management import _manager

pytestmark = pytest.mark.django_db


def test_project_manager_previews_applies_and_editor_cannot_administer(client, assignment_fixture):
    f = assignment_fixture
    _manager(f)
    f.scenario.access_mode = "inherit"
    f.scenario.save(update_fields=["access_mode"])
    url = reverse("console:project_access", args=[f.project.public_id])
    client.force_login(f.project_admin)
    assert client.get(url).status_code == 200
    page = client.post(
        url,
        {
            "action": "preview",
            f"member_{_membership(f.project_admin).pk}": P.MANAGER,
            f"member_{_membership(f.editor).pk}": P.EDITOR,
        },
    )
    assert page.status_code == 200 and page.context["preview"]
    assert not authorize(
        user=f.editor, capability=Capability.SCENARIO_EDIT, scenario=f.scenario
    ).allowed
    assert (
        client.post(
            url, {"action": "apply", "preview_token": page.context["preview"].token}
        ).status_code
        == 302
    )
    assert authorize(
        user=f.editor, capability=Capability.SCENARIO_EDIT, scenario=f.scenario
    ).allowed
    client.force_login(f.editor)
    assert client.get(url).status_code == 404
    assert client.post(url, {"action": "preview"}).status_code == 404
    client.force_login(f.project_admin)
    assert (
        client.get(reverse("console:project_access", args=[f.other_project.public_id])).status_code
        == 404
    )
    assert (
        client.post(
            url, {"action": "preview", f"member_{_membership(f.outsider).pk}": P.MANAGER}
        ).status_code
        == 400
    )


def test_new_scenario_requires_access_selection_and_creates_inherited_or_private(
    client, assignment_fixture
):
    f = assignment_fixture
    _manager(f)
    client.force_login(f.project_admin)
    url = reverse("console:project_scenario_create", args=[f.project.public_id])
    base = {"name": "New inherited", "preset": "empty_workflow", "logical_description": "Test flow"}
    assert client.get(url).context["form"]["access_mode"].value() == "inherit"
    assert client.post(url, base).status_code == 200
    assert not Scenario.objects.filter(name=base["name"]).exists()
    assert client.post(url, {**base, "access_mode": "inherit"}).status_code == 302
    inherited = Scenario.objects.get(name=base["name"])
    assert inherited.access_mode == "inherit"
    assert authorize(
        user=f.project_admin, capability=Capability.SCENARIO_RELEASE, scenario=inherited
    ).allowed
    private_data = {**base, "name": "New private", "access_mode": "private"}
    assert client.post(url, private_data).status_code == 200
    assert (
        client.post(
            url, {**private_data, "initial_manager": _membership(f.outsider).pk}
        ).status_code
        == 200
    )
    response = client.post(url, {**private_data, "initial_manager": _membership(f.editor).pk})
    assert response.status_code == 302
    private = Scenario.objects.get(name=private_data["name"])
    assert private.access_mode == "private"
    assert authorize(
        user=f.editor, capability=Capability.SCENARIO_RELEASE, scenario=private
    ).allowed
    assert not authorize(
        user=f.project_admin, capability=Capability.SCENARIO_VIEW, scenario=private
    ).allowed
    assert response.url == reverse("console:project_detail_public", args=[f.project.public_id])


def test_legacy_project_without_manager_gets_actionable_inheritance_error(
    client, assignment_fixture
):
    from apps.identity.assignment_services import grant_project_responsibility

    f = assignment_fixture
    grant_project_responsibility(
        project=f.project,
        membership=_membership(f.project_admin),
        responsibility=P.ADMINISTRATOR,
        actor=f.administrator,
    )
    client.force_login(f.project_admin)
    response = client.post(
        reverse("console:project_scenario_create", args=[f.project.public_id]),
        {
            "name": "No manager",
            "preset": "empty_workflow",
            "logical_description": "Test flow",
            "access_mode": "inherit",
        },
    )
    assert response.status_code == 200
    assert "önce projeye süresiz bir yönetici" in response.content.decode()
    assert not Scenario.objects.filter(name="No manager").exists()
