"""REST setup state, canonical mapping, exact authority and atomic persistence."""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.console.forms import BoundedJsonField
from apps.console.rest_setup_forms import InputStep, MappingStep, visual_initial
from apps.console.rest_setup_views import SESSION_KEY
from apps.documents.models import DocumentSet
from apps.ingestion.models import (
    ConnectorSyncSchedule,
    RestPullContract,
    Source,
    StagedIndexBuildJob,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest_schema import RestContractError
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.rest_setup import create_rest_setup
from apps.ingestion.tests.test_rest_pull import _definition
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.models import OrganizationMembership


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("mode", ["none", "page_number", "offset", "cursor"])
def test_visual_roundtrip_preserves_request_inputs_and_optional_mapping(method, mode):
    definition = _definition(method=method)
    definition["response"].update(deleted_pointer="/deleted", revision_pointer="")
    if mode != "none":
        definition["pagination"] = {"mode": mode, "parameter": "page", "page_size": 25}
        if mode == "cursor":
            definition["pagination"]["cursor_pointer"] = "/next"
    form = MappingStep(visual_initial(definition), method=method)
    assert form.is_valid(), form.errors
    assert form.definition == definition


def test_visual_roundtrip_preserves_detail_and_refuses_lossy_null_detail():
    definition = _definition()
    definition["response"].pop("content_pointer")
    definition["response"]["detail"] = {"path": "/docs/{input:id}", "content_pointer": ""}
    form = MappingStep(visual_initial(definition), method="GET")
    assert form.is_valid() and form.definition == definition
    definition = _definition()
    definition["response"]["detail"] = None
    with pytest.raises(RestContractError, match="ROUND_TRIP"):
        visual_initial(definition)


@pytest.mark.parametrize("path", ["https://private.example/docs", "/../secrets", "/%252e%252e/x"])
def test_visual_mode_cannot_bypass_canonical_authority_checks(path):
    data = visual_initial(_definition()) | {"path": path}
    assert not MappingStep(data, method="GET").is_valid()


def test_input_form_validates_real_types_and_false():
    definition = _definition()
    definition["inputs"].update(
        count={"type": "integer", "minimum": 1, "maximum": 5},
        flag={"type": "boolean"},
        group={"type": "enum", "values": ["a", "b"]},
    )
    data = {
        "input_dataset": "  docs  ",
        "input_count": "3",
        "input_flag": "false",
        "input_group": "a",
    }
    form = InputStep(data, definition=definition)
    assert form.is_valid(), form.errors
    assert form.inputs == {"dataset": "  docs  ", "count": 3, "flag": False, "group": "a"}
    for bad in ({"input_count": "6"}, {"input_flag": "anything"}, {"input_group": "c"}):
        assert not InputStep(data | bad, definition=definition).is_valid()


def test_deep_json_is_a_validation_error():
    with pytest.raises(ValidationError):
        BoundedJsonField(max_length=100000, max_depth=16).clean("[" * 2000 + "]" * 2000)


@pytest.mark.django_db
def test_synthetic_preview_does_not_persist_or_reflect_payload(client, wizard, governed_rest):
    advance(
        client, wizard, {"name": "Source", "profile": str(governed_rest[4].rest_profile.public_id)}
    )
    sample = {
        "data": {
            "items": [
                {
                    "id": "unreflected-id",
                    "revision": "v1",
                    "title": "unreflected-title",
                    "content": "unreflected-content",
                }
            ]
        }
    }
    result = advance(
        client,
        wizard,
        visual_initial(_definition()) | {"sample": json.dumps(sample)},
        action="preview",
    )
    assert result.status_code == 200 and result.context["preview_count"] == 1
    assert "unreflected" not in result.content.decode()
    assert "unreflected" not in json.dumps(client.session[SESSION_KEY])
    assert Source.objects.count() == 1
    sample["data"]["items"] *= 21
    result = advance(
        client,
        wizard,
        visual_initial(_definition()) | {"sample": json.dumps(sample)},
        action="preview",
    )
    assert result.status_code == 400 and "unreflected" not in result.content.decode()


@pytest.fixture
def wizard(client, governed_rest, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    client.force_login(governed_rest[1])
    response = client.get(reverse("console:rest_setup_new", args=[governed_rest[3].public_id]))
    assert response.status_code == 302
    return response.url


def advance(client, url, payload, action="next"):
    page = client.get(url)
    assert page.status_code == 200
    return client.post(url, payload | {"action": action, "submission": page.context["submission"]})


def to_review(client, url, setup):
    assert (
        advance(
            client,
            url,
            {"name": "Müşteri Destek Belgeleri", "profile": str(setup[4].rest_profile.public_id)},
        ).status_code
        == 302
    )
    assert advance(client, url, visual_initial(_definition())).status_code == 302
    assert advance(client, url, {"input_dataset": "private-dataset-value"}).status_code == 302
    page = client.get(url)
    assert page.context["step"] == 4
    return page


@pytest.mark.django_db
def test_full_flow_is_atomic_idempotent_redacted_and_has_no_dispatch(client, wizard, governed_rest):
    page = to_review(client, wizard, governed_rest)
    html = page.content.decode()
    assert (
        "private-dataset-value" not in html
        and "api.example.com" not in html
        and "secret:reader" not in html
    )
    assert page.context["navigation_section"] == "documents"
    payload = {"action": "save", "submission": page.context["submission"]}
    assert client.post(wizard, payload).status_code == 302
    assert client.post(wizard, payload).status_code == 302
    assert client.get(wizard).status_code == 302
    assert "private-dataset-value" not in json.dumps(client.session[SESSION_KEY])
    source = Source.objects.get(name="Müşteri Destek Belgeleri")
    assert source.rest_contract is not None
    assert source.connection_id and source.rest_contract.definition == _definition()
    assert not StagedIndexBuildJob.objects.filter(source=source).exists()
    assert RestPullContract.objects.count() == 2  # preexisting fixture + new contract


@pytest.mark.django_db
def test_back_refresh_advanced_roundtrip_and_stale_form(client, wizard, governed_rest):
    advance(
        client, wizard, {"name": "Source", "profile": str(governed_rest[4].rest_profile.public_id)}
    )
    old = client.get(wizard).context["submission"]
    assert (
        advance(client, wizard, visual_initial(_definition()), action="advanced").status_code == 302
    )
    page = client.get(wizard)
    assert json.loads(page.context["form"]["definition"].value()) == _definition()
    assert client.post(wizard, {"action": "next", "submission": old}).status_code == 400
    assert (
        advance(
            client, wizard, {"definition": json.dumps(_definition())}, action="visual"
        ).status_code
        == 302
    )
    assert client.get(wizard).context["mode"] == "visual"
    assert advance(client, wizard, {}, action="back").status_code == 302
    page = client.get(wizard)
    assert page.context["form"]["name"].value() == "Source"


@pytest.mark.django_db
def test_invalid_mapping_preserves_fields_and_cannot_save(client, wizard, governed_rest):
    advance(
        client, wizard, {"name": "Source", "profile": str(governed_rest[4].rest_profile.public_id)}
    )
    result = advance(client, wizard, visual_initial(_definition()) | {"path": "/../bad"})
    assert result.status_code == 400 and b"data-form-error-summary" in result.content
    assert result.context["form"]["path"].value() == "/../bad"
    assert Source.objects.count() == 1


@pytest.mark.django_db
def test_revoked_connection_cannot_complete_review(client, wizard, governed_rest):
    to_review(client, wizard, governed_rest)
    TenantRestPullProfileGrant.objects.all().delete()
    response = client.get(wizard)
    assert response.status_code == 200
    assert "Bağlantı izni bekleniyor" in response.content.decode()
    assert response.context["step"] == 4
    assert "private-dataset-value" not in response.content.decode()
    assert advance(client, wizard, {}, action="save").status_code == 200
    assert Source.objects.count() == 1


@pytest.mark.django_db
def test_exact_collection_actor_csrf_expiry_and_cookie_backend(
    client, wizard, governed_rest, settings
):
    other = DocumentSet.objects.create(
        organization=governed_rest[2], logical_id="other", name="Other"
    )
    assert client.get(reverse("console:rest_setup_new", args=[other.public_id])).status_code == 404
    stranger = get_user_model().objects.create_user("neighbor")
    OrganizationMembership.objects.create(organization=governed_rest[2], user=stranger)
    stranger_client = Client()
    stranger_client.force_login(stranger)
    assert stranger_client.get(wizard).status_code == 404
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(governed_rest[1])
    assert csrf_client.post(wizard, {}).status_code == 403
    session = client.session
    for state in session[SESSION_KEY].values():
        state["created"] = 0
    session.save()
    assert client.get(wizard).status_code == 400
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
    cookie_client = Client()
    cookie_client.force_login(governed_rest[1])
    assert cookie_client.get(wizard).status_code == 404


@pytest.mark.django_db
def test_draft_count_and_feature_gate(client, wizard, governed_rest, settings):
    url = reverse("console:rest_setup_new", args=[governed_rest[3].public_id])
    for _ in range(7):
        assert client.get(url).status_code == 302
    assert len(client.session[SESSION_KEY]) == 5
    assert client.get(wizard).status_code == 400
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    assert client.get(url).status_code == 404


def bundle_args(setup):
    return {
        "actor": setup[1],
        "document_set": setup[3],
        "profile_id": setup[4].rest_profile.public_id,
        "intent": uuid4(),
        "name": "Atomic source",
        "definition": _definition(),
        "inputs": {"dataset": "legal"},
    }


@pytest.mark.django_db
def test_bundle_rolls_back_contract_if_source_or_audit_fails(governed_rest, monkeypatch):
    import apps.ingestion.rest_setup as module

    def fail(**kwargs):
        raise RestServiceError("INJECTED_FAILURE")

    monkeypatch.setattr(module, "create_rest_source", fail)
    with pytest.raises(RestServiceError, match="INJECTED_FAILURE"):
        create_rest_setup(**bundle_args(governed_rest))
    assert RestPullContract.objects.count() == 1 and Source.objects.count() == 1


@pytest.mark.django_db
def test_bundle_reauthorizes_replays_and_rejects_payload_conflict(governed_rest):
    args = bundle_args(governed_rest)
    original = create_rest_setup(**args)
    assert create_rest_setup(**args).pk == original.pk
    with pytest.raises(RestServiceError, match="INTENT_CONFLICT"):
        create_rest_setup(**(args | {"inputs": {"dataset": "other"}}))
    TenantRestPullProfileGrant.objects.all().delete()
    with pytest.raises(RestAuthorizationError):
        create_rest_setup(**args)
    denied = AuditEvent.objects.filter(action="rest_source.setup").latest("pk")
    assert denied.outcome == "deny"
    assert "legal" not in str(denied.after)


@pytest.mark.django_db
def test_periodic_draft_schedule_is_atomic_and_exact_on_replay(governed_rest):
    from django.utils import timezone

    arguments = bundle_args(governed_rest) | {"schedule": {"interval_seconds": 3600}}
    before = timezone.now()
    source = create_rest_setup(**arguments)
    schedule = ConnectorSyncSchedule.objects.get(source=source)
    assert schedule.enabled and schedule.automation_mode == "draft_only"
    assert 3599 <= (schedule.next_run_at - before).total_seconds() <= 3605
    assert schedule.embedding_profile_id is None and not schedule.promotion_targets.exists()
    assert create_rest_setup(**arguments).pk == source.pk
    with pytest.raises(RestServiceError, match="INTENT_CONFLICT"):
        create_rest_setup(**(arguments | {"schedule": None}))
    assert not StagedIndexBuildJob.objects.exists()


@pytest.mark.django_db
def test_forged_automation_or_invalid_interval_cannot_create(governed_rest):
    for schedule in (
        {"interval_seconds": 1},
        {"interval_seconds": True},
        {"interval_seconds": 900, "automation_mode": "promote_if_safe"},
    ):
        with pytest.raises(RestServiceError, match="SCHEDULE_INVALID"):
            create_rest_setup(**(bundle_args(governed_rest) | {"schedule": schedule}))
    assert Source.objects.count() == 1 and RestPullContract.objects.count() == 1


@pytest.mark.django_db
def test_periodic_wizard_keeps_choice_on_back_and_records_schedule(client, wizard, governed_rest):
    advance(
        client,
        wizard,
        {"name": "Scheduled source", "profile": str(governed_rest[4].rest_profile.public_id)},
    )
    advance(client, wizard, visual_initial(_definition()))
    invalid = advance(client, wizard, {"input_dataset": "kb", "sync_mode": "periodic"})
    assert invalid.status_code == 400
    advance(
        client, wizard, {"input_dataset": "kb", "sync_mode": "periodic", "interval_seconds": "3600"}
    )
    page = client.get(wizard)
    assert "Saatte bir" in page.content.decode()
    advance(client, wizard, {}, action="back")
    page = client.get(wizard)
    assert page.context["form"]["sync_mode"].value() == "periodic"
    advance(
        client, wizard, {"input_dataset": "kb", "sync_mode": "periodic", "interval_seconds": "3600"}
    )
    saved = advance(client, wizard, {}, action="save")
    assert saved.status_code == 302
    schedule = ConnectorSyncSchedule.objects.get(source__name="Scheduled source")
    assert schedule.interval_seconds == 3600
    detail = client.get(saved.url)
    assert detail.context["schedule"].pk == schedule.pk
    assert "Sonraki yenileme:" in detail.content.decode()


@pytest.mark.django_db
def test_source_audit_failure_rolls_back_entire_setup(governed_rest, monkeypatch):
    import apps.ingestion.rest_services as module

    original = module._audit

    def unavailable(action, *args, **kwargs):
        if action == "rest_source.create":
            raise RuntimeError("audit unavailable")
        return original(action, *args, **kwargs)

    monkeypatch.setattr(module, "_audit", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_rest_setup(**bundle_args(governed_rest))
    assert Source.objects.count() == 1 and RestPullContract.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_intent_creates_one_contract_and_source(governed_rest):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL organization row lock")
    args = bundle_args(governed_rest)

    def save():
        close_old_connections()
        try:
            return create_rest_setup(**args).pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(save) for _ in range(2)]
        assert attempts[0].result() == attempts[1].result()
    assert Source.objects.count() == 2 and RestPullContract.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_probe_http_has_real_csrf_and_committed_transport_boundary(
    client, wizard, governed_rest, monkeypatch
):
    from apps.ingestion.tests.test_rest_probe import wire

    page = to_review(client, wizard, governed_rest)
    url = page.context["probe_url"]
    assert client.get(url).status_code == 405
    assert client.post(url, {"submission": "tampered"}).status_code == 400
    upstream = wire(monkeypatch)
    secure = Client(enforce_csrf_checks=True)
    secure.cookies = client.cookies
    payload = {"submission": page.context["submission"]}
    assert secure.post(url, payload).status_code == 403
    payload["csrfmiddlewaretoken"] = secure.cookies["csrftoken"].value
    response = secure.post(url, payload, follow=True)
    assert response.status_code == 200
    assert "ilk yanıtında 1 belge eşlendi" in response.content.decode()
    assert len(upstream.requests) == 1
    assert Source.objects.count() == 1
    assert not StagedIndexBuildJob.objects.exists()
    assert secure.post(url, payload).status_code == 302
    assert len(upstream.requests) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("schedule", [None, {"interval_seconds": 900}])
def test_bundle_works_with_readonly_profile_catalog_and_forced_rls(governed_rest, schedule):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RLS and grants")
    role = f"rest_setup_{uuid4().hex}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT DELETE ON ingestion_connectorschedulepromotiontarget TO "{role}"')
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_restpullprofile, ingestion_connection "
            f'FROM "{role}"'
        )
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        source = create_rest_setup(**(bundle_args(governed_rest) | {"schedule": schedule}))
        assert source.connection_id
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
