import pytest
from django.urls import reverse

from apps.documents.access_services import grant_scenario_document_set_access_if_authorized
from apps.documents.models import ScenarioDocumentSetBinding
from apps.documents.shared_access import set_scenario_data_access_mode
from apps.documents.tests.test_scenario_access import access_fixture as access_fixture

pytestmark = pytest.mark.django_db


def _setup(f):
    grant = grant_scenario_document_set_access_if_authorized(
        scenario=f["scenario"], document_set=f["document_set"], actor=f["manager"]
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=f["organization"], scenario=f["scenario"], document_set=f["document_set"]
    )
    return grant


def test_data_owner_can_acknowledge_and_revoke_but_scenario_author_and_org_admin_cannot(
    client, access_fixture
):
    f = access_fixture
    grant = _setup(f)
    url = reverse("console:document_shared_access", args=[f["document_set"].public_id])
    for actor in (f["project_admin"], f["admin"]):
        client.force_login(actor)
        assert client.get(url).status_code == 404
        assert (
            client.post(
                url, {"grant_id": grant.pk, "action": "approve", "acknowledge": "yes"}
            ).status_code
            == 404
        )
    client.force_login(f["manager"])
    assert client.get(url).status_code == 200
    assert client.post(url, {"grant_id": grant.pk, "action": "approve"}).status_code == 400
    assert (
        client.post(
            url, {"grant_id": grant.pk, "action": "approve", "acknowledge": "yes"}
        ).status_code
        == 302
    )
    grant.refresh_from_db()
    assert grant.shared_consumers
    assert (
        client.post(
            url, {"grant_id": "9" * 5000, "action": "approve", "acknowledge": "yes"}
        ).status_code
        == 404
    )
    assert client.post(url, {"grant_id": grant.pk, "action": "revoke"}).status_code == 302
    grant.refresh_from_db()
    assert not grant.shared_consumers


def test_scenario_form_requires_explicit_mode_confirmation_and_reports_missing_set_consent(
    client, access_fixture
):
    f = access_fixture
    _setup(f)
    url = reverse("console:scenario_data_access", args=[f["scenario"].public_id])
    client.force_login(f["project_admin"])
    page = client.get(url)
    assert page.status_code == 200
    assert "Veri yöneticisinin ortak kullanım onayı gerekli" in page.content.decode()
    payload = {"mode": "scenario_shared", "mode_token": page.context["mode_token"]}
    assert client.post(url, payload).status_code == 400
    assert (
        client.post(url, {**payload, "confirm": "yes", "mode_token": "forged"}).status_code == 400
    )
    assert client.post(url, {**payload, "confirm": "yes"}).status_code == 302
    f["scenario"].refresh_from_db()
    assert f["scenario"].data_access_mode == "scenario_shared"
    assert "Veri yöneticisinin ortak kullanım onayı gerekli" in client.get(url).content.decode()
    client.force_login(f["admin"])
    assert client.get(url).status_code == 200
    assert client.post(url, {**payload, "confirm": "yes"}).status_code == 404


def test_foreign_set_ids_and_stale_mode_form_cannot_change_scope(client, access_fixture):
    f = access_fixture
    _setup(f)
    client.force_login(f["manager"])
    assert (
        client.get(
            reverse("console:document_shared_access", args=[f["foreign_set"].public_id])
        ).status_code
        == 404
    )
    client.force_login(f["project_admin"])
    url = reverse("console:scenario_data_access", args=[f["scenario"].public_id])
    token = client.get(url).context["mode_token"]
    set_scenario_data_access_mode(
        scenario=f["scenario"], actor=f["project_admin"], mode="scenario_shared"
    )
    response = client.post(
        url, {"mode": "consumer_specific", "confirm": "yes", "mode_token": token}
    )
    assert response.status_code == 400
    assert "Veri erişim düzeni değişti" in response.content.decode()
    f["scenario"].refresh_from_db()
    assert f["scenario"].data_access_mode == "scenario_shared"
