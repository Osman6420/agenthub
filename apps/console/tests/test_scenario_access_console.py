"""Real HTTP/form authorization for access previews and the parent navigation shell."""

import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import Scenario
from apps.identity.assignment_services import grant_scenario_responsibility
from apps.identity.models import ScenarioResponsibility
from apps.identity.tests.test_delegated_assignments import _membership
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture
from apps.identity.tests.test_inherited_assignment_management import _manager

pytestmark = pytest.mark.django_db


def _url(scenario):
    return reverse("console:scenario_access", args=[scenario.public_id])


def test_manager_previews_and_applies_private_access_without_seeing_private_definition(
    client, assignment_fixture
):
    f = assignment_fixture
    _manager(f)
    client.force_login(f.project_admin)
    page = client.get(_url(f.scenario))
    assert page.status_code == 200
    preview = client.post(
        _url(f.scenario),
        {
            "action": "preview",
            "mode": "private",
            f"member_{_membership(f.editor).pk}": ScenarioResponsibility.MANAGER,
        },
    )
    assert preview.status_code == 200
    token = preview.context["preview"].token
    assert "Değişiklik önizlemesi" in preview.content.decode()
    f.scenario.refresh_from_db()
    assert f.scenario.access_mode == "legacy"
    response = client.post(_url(f.scenario), {"action": "apply", "preview_token": token})
    assert response.status_code == 302
    f.scenario.refresh_from_db()
    assert f.scenario.access_mode == "private"
    assert (
        client.get(
            reverse("console:scenario_detail_public", args=[f.scenario.public_id])
        ).status_code
        == 404
    )
    assert client.get(_url(f.scenario)).status_code == 200
    client.force_login(f.editor)
    assert client.get(_url(f.scenario)).status_code == 200
    assert (
        AuditEvent.objects.filter(
            action="responsibility.scenario.access_changed", outcome="success"
        ).count()
        == 1
    )


def test_viewer_foreign_scope_and_forged_member_cannot_change_access(client, assignment_fixture):
    f = assignment_fixture
    _manager(f)
    grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.VIEWER,
        actor=f.administrator,
    )
    client.force_login(f.editor)
    assert client.get(_url(f.scenario)).status_code == 404
    assert (
        client.post(_url(f.scenario), {"action": "apply", "preview_token": "forged"}).status_code
        == 404
    )
    client.force_login(f.project_admin)
    assert client.get(_url(f.other_scenario)).status_code == 404
    forged = client.post(
        _url(f.scenario),
        {
            "action": "preview",
            "mode": "private",
            f"member_{_membership(f.editor).pk}": ScenarioResponsibility.MANAGER,
            f"member_{_membership(f.outsider).pk}": ScenarioResponsibility.MANAGER,
        },
    )
    assert forged.status_code == 400 and forged.context["preview"] is None
    client.force_login(f.outsider)
    assert client.get(_url(f.scenario)).status_code == 404


def test_parent_shell_never_renders_siblings_or_project_administration(client, assignment_fixture):
    f = assignment_fixture
    f.project.owner = "private-owner-label"
    f.project.data_classification = "private-classification"
    f.project.save()
    sibling = Scenario.objects.create(
        organization=f.organization,
        project=f.project,
        slug="hidden",
        name="Hidden sibling definition",
    )
    grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.VIEWER,
        actor=f.administrator,
    )
    client.force_login(f.editor)
    response = client.get(reverse("console:project_detail_public", args=[f.project.public_id]))
    assert response.status_code == 200
    html = response.content.decode()
    assert f.scenario.name in html
    assert sibling.name not in html
    assert "private-owner-label" not in html and "private-classification" not in html
    assert response.context["project_shell_only"] is True
    assert "Proje erişimi" not in html


def test_stale_preview_is_explained_and_does_not_change_mode(client, assignment_fixture):
    f = assignment_fixture
    _manager(f)
    client.force_login(f.project_admin)
    response = client.post(_url(f.scenario), {"action": "preview", "mode": "inherit"})
    assert response.status_code == 200
    token = response.context["preview"].token
    grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=f.administrator,
    )
    response = client.post(_url(f.scenario), {"action": "apply", "preview_token": token})
    assert response.status_code == 400
    assert "Erişim bilgileri değişti" in response.content.decode()
    f.scenario.refresh_from_db()
    assert f.scenario.access_mode == "legacy"


def test_inherited_scenario_does_not_preselect_ineffective_old_direct_roles(
    client, assignment_fixture
):
    f = assignment_fixture
    _manager(f)
    grant_scenario_responsibility(
        scenario=f.scenario,
        membership=_membership(f.editor),
        responsibility=ScenarioResponsibility.EDITOR,
        actor=f.administrator,
    )
    f.scenario.access_mode = "inherit"
    f.scenario.save(update_fields=["access_mode"])
    client.force_login(f.project_admin)
    response = client.get(_url(f.scenario))
    assert response.status_code == 200
    assert not response.context["form"][f"member_{_membership(f.editor).pk}"].value()
