from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.catalog.models import AIProject, Scenario
from apps.documents import services as document_services
from apps.documents import storage
from apps.documents.models import (
    DocumentSet,
    DocumentSetStatus,
    DocumentSetVersionStatus,
    DocumentVersion,
)
from apps.documents.services import bind_scenario_document_set
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
)
from apps.ingestion.automation import ConnectorAutomationError, claim_connector_automation
from apps.ingestion.embedding_services import grant_embedding_profile, register_embedding_profile
from apps.ingestion.models import (
    ConnectorAutomationStatus,
    ConnectorType,
    IndexVersion,
    RestPullAuthMode,
    RestPullContract,
    RestSyncRun,
    RestSyncStatus,
    Source,
)
from apps.ingestion.rest import GovernedRestClient, RestPullError, RestPullItem
from apps.ingestion.rest_schema import RestContractError, render_path, validate_contract
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
    create_rest_contract,
    create_rest_source,
    create_rest_sync_run,
    disable_rest_profile,
    grant_rest_profile,
    register_rest_profile,
)
from apps.ingestion.rest_sync import execute_rest_sync
from apps.ingestion.scheduler import dispatch_due_schedules
from apps.ingestion.tasks import apply_connector_automation_task
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tools.http_adapter import ConnectionFactory


def _definition(*, method: str = "GET") -> dict[str, Any]:
    return {
        "version": 1,
        "inputs": {"dataset": {"type": "string", "max_length": 64}},
        "request": {
            "method": method,
            "path": "/datasets/{input:dataset}/documents",
            "query": {"include": "content"},
            **({"body": {"dataset": {"$input": "dataset"}}} if method == "POST" else {}),
        },
        "response": {
            "items_pointer": "/data/items",
            "id_pointer": "/id",
            "revision_pointer": "/revision",
            "title_pointer": "/title",
            "content_pointer": "/content",
            "content_encoding": "utf8_text",
            "mime_type": "text/markdown",
        },
        "pagination": {"mode": "none"},
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["request"].update({"headers": {"Authorization": "x"}}),
        lambda value: value["request"].update({"path": "https://attacker.example/x"}),
        lambda value: value["request"].update({"path": "/x/%2e%2e/admin"}),
        lambda value: value["request"].update({"query": {"x": "{{ code }}"}}),
        lambda value: value["response"].update({"items_pointer": "$..items"}),
    ],
)
def test_contract_rejects_authority_and_executable_mapping(mutation: Any) -> None:
    definition = _definition()
    mutation(definition)
    with pytest.raises(RestContractError):
        validate_contract(definition)


def test_path_inputs_are_one_encoded_segment() -> None:
    assert render_path("/datasets/{input:dataset}/docs", {"dataset": "a/b ?"}) == (
        "/datasets/a%2Fb%20%3F/docs"
    )


@pytest.mark.django_db
def test_profile_rejects_encoded_or_query_path_prefix() -> None:
    platform = get_user_model().objects.create_superuser(username="prefix-admin", password=None)
    fields = {
        "logical_id": "invalid-prefix",
        "revision": 1,
        "method": "GET",
        "auth_mode": "none",
        "secret_ref": "",
        "api_key_header_name": "",
        "timeout_seconds": 30,
        "max_response_bytes": 1_000_000,
        "max_total_bytes": 10_000_000,
        "max_requests": 100,
        "max_items": 100,
        "max_pages": 10,
        "max_retries": 1,
        "max_decoded_item_bytes": 1_000_000,
    }
    for prefix in ("/api/%2e%2e/admin", "/api?admin=true"):
        with pytest.raises(ValueError, match="REST_PATH_PREFIX_INVALID"):
            register_rest_profile(
                actor=platform,
                base_url="https://api.example.com",
                path_prefix=prefix,
                **fields,
            )


class _Response:
    def __init__(
        self, status: int, payload: object, content_type: str = "application/json"
    ) -> None:
        self.status = status
        self.body = json.dumps(payload).encode()
        self.content_type = content_type

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def getheader(self, name: str, default: str = "") -> str:
        return self.content_type if name.lower() == "content-type" else default


class _Connection:
    def __init__(self, response: _Response | None = None, *, uncertain: bool = False) -> None:
        self.response = response
        self.uncertain = uncertain
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []

    def request(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> None:
        self.requests.append((method, url, body, headers))

    def getresponse(self) -> _Response:
        if self.uncertain:
            raise TimeoutError
        assert self.response is not None
        return self.response

    def close(self) -> None:
        pass


class _Factory:
    def __init__(self, *connections: _Connection) -> None:
        self.connections = list(connections)
        self.used: list[_Connection] = []

    def __call__(self, ip: str, port: int, timeout: float, hostname: str) -> _Connection:
        assert (ip, port, hostname) == ("8.8.8.8", 443, "api.example.com")
        connection = self.connections.pop(0)
        self.used.append(connection)
        return connection


class _Secrets:
    def resolve(self, ref: str) -> str:
        assert ref == "secret:reader"
        return "credential"  # noqa: S105


def _resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", ("8.8.8.8", port))]


def _profile(method: str = "GET") -> Any:
    return SimpleNamespace(
        scheme="https",
        host="api.example.com",
        port=443,
        path_prefix="/api/v1",
        method=method,
        auth_mode=RestPullAuthMode.BEARER,
        secret_ref="secret:reader",  # noqa: S106
        api_key_header_name="",
        timeout_seconds=5,
        max_response_bytes=100_000,
        max_total_bytes=200_000,
        max_requests=10,
        max_items=10,
        max_pages=2,
        max_retries=2,
        max_decoded_item_bytes=100_000,
    )


def test_client_uses_fixed_profile_path_and_ignores_response_url() -> None:
    connection = _Connection(
        _Response(
            200,
            {
                "data": {
                    "items": [
                        {
                            "id": "1",
                            "revision": "2",
                            "title": "Doc",
                            "content": "safe",
                            "url": "https://attacker.example/private",
                        }
                    ]
                }
            },
        )
    )
    client = GovernedRestClient(
        resolver=_resolver,
        connection_factory=cast(ConnectionFactory, _Factory(connection)),
        secret_resolver=_Secrets(),
    )
    contract = cast(RestPullContract, SimpleNamespace(definition=_definition()))

    items = list(client.iter_items(_profile(), contract, inputs={"dataset": "legal/a"}))

    assert items[0].external_id == "1"
    assert (
        client.get_content(_profile(), contract, items[0], inputs={"dataset": "legal/a"}) == b"safe"
    )
    method, path, body, headers = connection.requests[0]
    assert method == "GET" and body is None
    assert path == "/api/v1/datasets/legal%2Fa/documents?include=content"
    assert "attacker.example" not in path
    assert headers["Authorization"] == "Bearer credential"


def test_post_uncertain_is_not_retried() -> None:
    factory = _Factory(_Connection(uncertain=True))
    client = GovernedRestClient(
        resolver=_resolver,
        connection_factory=cast(ConnectionFactory, factory),
        secret_resolver=_Secrets(),
        sleeper=lambda seconds: None,
    )
    with pytest.raises(RestPullError, match="REST_POST_OUTCOME_UNKNOWN"):
        list(
            client.iter_items(
                _profile("POST"),
                cast(RestPullContract, SimpleNamespace(definition=_definition(method="POST"))),
                inputs={"dataset": "legal"},
            )
        )
    assert len(factory.used) == 1


def test_detail_fetch_is_forbidden_for_post_profile() -> None:
    definition = _definition(method="POST")
    definition["response"].pop("content_pointer")
    definition["response"]["detail"] = {
        "path": "/documents/{input:id}",
        "content_pointer": "/content",
    }
    validate_contract(definition)
    client = GovernedRestClient(
        resolver=_resolver,
        connection_factory=cast(ConnectionFactory, _Factory()),
        secret_resolver=_Secrets(),
    )

    with pytest.raises(RestPullError, match="REST_DETAIL_REQUIRES_GET_PROFILE"):
        client.get_content(
            _profile("POST"),
            cast(RestPullContract, SimpleNamespace(definition=definition)),
            RestPullItem("doc-1", "r1", "Doc", False, None),
            inputs={"dataset": "legal"},
        )


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


@pytest.fixture
def governed_rest(db: Any) -> tuple[Any, Any, Organization, DocumentSet, Any]:
    organization = Organization.objects.create(slug="rest", name="REST")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="kb", name="Knowledge Base"
    )
    platform = get_user_model().objects.create_superuser(username="platform", password=None)
    author = get_user_model().objects.create_user(username="author")
    OrganizationMembership.objects.create(organization=organization, user=author)
    profile = register_rest_profile(
        actor=platform,
        base_url="https://api.example.com",
        path_prefix="/api/v1",
        logical_id="kb-api",
        revision=1,
        method="GET",
        auth_mode="bearer",
        secret_ref="secret:reader",  # noqa: S106
        api_key_header_name="",
        timeout_seconds=30,
        max_response_bytes=1_000_000,
        max_total_bytes=10_000_000,
        max_requests=100,
        max_items=100,
        max_pages=10,
        max_retries=1,
        max_decoded_item_bytes=1_000_000,
    )
    grant_rest_profile(
        actor=platform,
        organization=organization,
        document_set=document_set,
        rest_profile=profile,
    )
    contract = create_rest_contract(
        actor=author,
        organization=organization,
        logical_id="kb-contract",
        revision=1,
        definition=_definition(),
    )
    source = create_rest_source(
        actor=author,
        organization=organization,
        document_set=document_set,
        rest_profile=profile,
        rest_contract=contract,
        slug="kb-api",
        name="KB API",
        inputs={"dataset": "legal"},
    )
    return platform, author, organization, document_set, source


class _SyncClient:
    def __init__(self, items: list[RestPullItem], contents: dict[str, bytes]) -> None:
        self.items = items
        self.contents = contents
        self.detail_calls: list[str] = []

    @property
    def fetched_bytes(self) -> int:
        return sum(len(value) for value in self.contents.values())

    def iter_items(
        self, profile: Any, contract: Any, *, inputs: dict[str, object]
    ) -> Iterator[RestPullItem]:
        yield from self.items

    def get_content(
        self,
        profile: Any,
        contract: Any,
        item: RestPullItem,
        *,
        inputs: dict[str, object],
    ) -> bytes:
        self.detail_calls.append(item.external_id)
        return self.contents[item.external_id]


def test_quarantined_set_rejects_new_rest_sync(governed_rest: Any) -> None:
    _platform, author, _organization, document_set, source = governed_rest
    document_set.status = DocumentSetStatus.QUARANTINED
    document_set.save(update_fields=["status", "updated_at"])

    with pytest.raises(RestServiceError, match="DOCUMENT_SET_QUARANTINED"):
        create_rest_sync_run(actor=author, source=source)


@pytest.mark.django_db
def test_sync_reuses_checksum_preserves_other_members_and_noops(governed_rest: Any) -> None:
    _, author, organization, document_set, source = governed_rest
    base = document_services.create_document_set_version(
        document_set=document_set, actor="operator"
    )
    upload = document_services.upload_document(
        organization=organization,
        logical_id="manual",
        title="Manual",
        mime_type="text/markdown",
        data=b"manual",
        actor="operator",
        document_set_version=base,
    )
    document_services.add_document_to_set_version(
        set_version=base, document_version=upload, actor="operator"
    )
    document_services.publish_document_set_version(set_version=base, actor="operator")
    first = create_rest_sync_run(actor=author, source=source)
    first_client = _SyncClient(
        [RestPullItem("doc-1", "r1", "Doc", False, "unused")],
        {"doc-1": b"same body"},
    )
    assert execute_rest_sync(first.pk, organization_id=organization.pk, client=first_client) == (
        RestSyncStatus.SUCCEEDED
    )
    first.refresh_from_db()
    assert first.material_change and first.candidate_set_version_id
    assert first.candidate_set_version is not None
    members = list(
        first.candidate_set_version.memberships.order_by("ordinal").values_list(
            "document_version_id", flat=True
        )
    )
    assert members[0] == upload.pk and len(members) == 2

    second = create_rest_sync_run(actor=author, source=source)
    second_client = _SyncClient(
        [RestPullItem("doc-1", "r2", "Doc renamed", False, "unused")],
        {"doc-1": b"same body"},
    )
    execute_rest_sync(second.pk, organization_id=organization.pk, client=second_client)
    second.refresh_from_db()
    assert second.status == RestSyncStatus.SUCCEEDED
    assert second.material_change is False and second.candidate_set_version_id is None
    assert DocumentVersion.objects.filter(document__source=source).count() == 1

    third = create_rest_sync_run(actor=author, source=source)
    fast_path = _SyncClient(
        [RestPullItem("doc-1", "r2", "Doc renamed", False, "unused")],
        {"doc-1": b"must not be read"},
    )
    execute_rest_sync(third.pk, organization_id=organization.pk, client=fast_path)
    assert fast_path.detail_calls == []


@pytest.mark.django_db
def test_profile_grant_and_author_role_are_deny_by_default(governed_rest: Any) -> None:
    _, _, organization, document_set, source = governed_rest
    outsider = get_user_model().objects.create_user(username="outsider")
    with pytest.raises(RestAuthorizationError, match="SCENARIO_AUTHOR_REQUIRED"):
        create_rest_sync_run(actor=outsider, source=source)
    assert source.connector_type == ConnectorType.GENERIC_REST
    assert document_set.organization_id == organization.id


@pytest.mark.django_db
def test_disabled_profile_rejects_new_runs(governed_rest: Any) -> None:
    platform, author, _, _, source = governed_rest
    disable_rest_profile(actor=platform, rest_profile=source.rest_profile)

    with pytest.raises(ValueError, match="REST_PROFILE_DISABLED"):
        create_rest_sync_run(actor=author, source=source)


@pytest.mark.django_db(transaction=True)
def test_non_governed_source_cannot_bind_document_set(governed_rest: Any) -> None:
    _, _, organization, document_set, _ = governed_rest
    with pytest.raises(IntegrityError), transaction.atomic():
        Source.objects.create(
            organization=organization,
            slug="invalid-https-binding",
            name="Invalid HTTPS binding",
            connector_type=ConnectorType.HTTPS,
            connector_config={},
            document_set=document_set,
        )


@pytest.mark.django_db(transaction=True)
def test_schedule_dispatches_one_slot_without_backlog(
    governed_rest: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, author, organization, _, source = governed_rest
    now = timezone.now()
    schedule = configure_sync_schedule(
        actor=author,
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=now - timedelta(days=2),
    )
    enqueued: list[int] = []
    monkeypatch.setattr(
        "apps.ingestion.scheduler._enqueue_on_commit",
        lambda schedule, run_id: enqueued.append(run_id),
    )

    assert dispatch_due_schedules(now=now) == 1
    assert dispatch_due_schedules(now=now) == 0
    schedule.refresh_from_db()
    run = RestSyncRun.objects.get(schedule=schedule)
    assert run.status == RestSyncStatus.QUEUED
    assert schedule.next_run_at == now + timedelta(seconds=900)
    assert run.schedule_slot == now - timedelta(days=2)
    assert enqueued == [run.pk]

    # A broker-lost queued delivery is redriven at the next interval without
    # creating a second run or replaying the stale backlog.
    assert dispatch_due_schedules(now=now + timedelta(seconds=900)) == 1
    assert RestSyncRun.objects.filter(schedule=schedule).count() == 1
    assert enqueued == [run.pk, run.pk]


@pytest.mark.django_db
def test_schedule_rejects_unapproved_automatic_promotion(governed_rest: Any) -> None:
    _, author, _, _, source = governed_rest
    with pytest.raises(RestAuthorizationError, match="RELEASE_MANAGER_REQUIRED"):
        configure_sync_schedule(
            actor=author,
            source=source,
            interval_seconds=900,
            enabled=True,
            next_run_at=timezone.now(),
            automation_mode="promote_if_safe",
            scenarios=[],
        )


@pytest.mark.django_db(transaction=True)
def test_schedule_does_not_queue_behind_manual_pending_run(
    governed_rest: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, author, _, _, source = governed_rest
    pending = create_rest_sync_run(actor=author, source=source)
    now = timezone.now()
    schedule = configure_sync_schedule(
        actor=author,
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=now,
    )
    enqueued: list[int] = []
    monkeypatch.setattr(
        "apps.ingestion.scheduler._enqueue_on_commit",
        lambda schedule, run_id: enqueued.append(run_id),
    )

    assert dispatch_due_schedules(now=now) == 0
    assert RestSyncRun.objects.filter(source=source).count() == 1
    assert RestSyncRun.objects.get(source=source).pk == pending.pk
    assert enqueued == []
    schedule.refresh_from_db()
    assert schedule.next_run_at == now + timedelta(seconds=900)


@pytest.mark.django_db
def test_document_set_manager_can_select_exact_safe_promotion_target(governed_rest: Any) -> None:
    platform, _, organization, document_set, source = governed_rest
    manager = get_user_model().objects.create_user(username="release-manager")
    membership = OrganizationMembership.objects.create(
        organization=organization,
        user=manager,
    )
    assignment = DocumentSetResponsibilityAssignment.objects.create(
        organization=organization,
        document_set=document_set,
        membership=membership,
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=platform,
    )
    project = AIProject.objects.create(organization=organization, slug="p", name="P")
    scenario = Scenario.objects.create(project=project, slug="rag", name="RAG")
    bind_scenario_document_set(scenario=scenario, document_set=document_set, actor=str(manager.pk))
    embedding_profile = register_embedding_profile(
        actor=platform,
        logical_id="embed",
        revision=1,
        provider="openai_compatible",
        scheme="https",
        host="embedding.example.com",
        port=443,
        path="/v1/embeddings",
        model="deterministic",
        secret_ref="secret:embedding",  # noqa: S106
        dimensions=64,
        index_type="vector",
        normalize=True,
        distance_metric="cosine",
        timeout_seconds=30,
        max_response_bytes=1_000_000,
        max_batch_size=64,
    )
    grant_embedding_profile(
        actor=platform,
        organization=organization,
        embedding_profile=embedding_profile,
    )

    schedule = configure_sync_schedule(
        actor=manager,
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=timezone.now(),
        automation_mode="promote_if_safe",
        embedding_profile=embedding_profile,
        scenarios=[scenario],
    )

    assert schedule.promotion_approved_by == str(manager.pk)
    assert list(schedule.promotion_targets.values_list("scenario_id", flat=True)) == [scenario.pk]

    candidate = document_services.create_document_set_version(
        document_set=document_set, actor="operator"
    )
    version = document_services.upload_document(
        organization=organization,
        logical_id="revoked-candidate",
        title="Candidate",
        mime_type="text/markdown",
        data=b"candidate",
        actor="operator",
        document_set_version=candidate,
    )
    document_services.add_document_to_set_version(
        set_version=candidate, document_version=version, actor="operator"
    )
    assignment.delete()

    with pytest.raises(RuntimeError, match="AUTOMATION_RELEASE_MANAGER_REVOKED"):
        apply_connector_automation_task.run(schedule.pk, candidate.pk, organization.pk)
    candidate.refresh_from_db()
    assert candidate.status == DocumentSetVersionStatus.DRAFT
    assert not IndexVersion.objects.filter(document_set_version=candidate).exists()


@pytest.mark.django_db
def test_automation_task_is_idempotent_per_candidate(governed_rest: Any) -> None:
    _, author, organization, document_set, source = governed_rest
    candidate = document_services.create_document_set_version(
        document_set=document_set, actor="operator"
    )
    version = document_services.upload_document(
        organization=organization,
        logical_id="candidate-doc",
        title="Candidate",
        mime_type="text/markdown",
        data=b"candidate",
        actor="operator",
        document_set_version=candidate,
    )
    document_services.add_document_to_set_version(
        set_version=candidate, document_version=version, actor="operator"
    )
    schedule = configure_sync_schedule(
        actor=author,
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=timezone.now(),
        automation_mode="draft_only",
    )

    first = apply_connector_automation_task.run(schedule.pk, candidate.pk, organization.pk)
    second = apply_connector_automation_task.run(schedule.pk, candidate.pk, organization.pk)

    schedule.refresh_from_db()
    assert first == "draft_only" and second == "already_processed"
    assert schedule.automation_status == ConnectorAutomationStatus.SUCCEEDED


@pytest.mark.django_db
def test_stale_automation_claim_is_recoverable(governed_rest: Any) -> None:
    _, author, organization, document_set, source = governed_rest
    candidate = document_services.create_document_set_version(
        document_set=document_set, actor="operator"
    )
    version = document_services.upload_document(
        organization=organization,
        logical_id="recovery-doc",
        title="Recovery",
        mime_type="text/markdown",
        data=b"recovery",
        actor="operator",
        document_set_version=candidate,
    )
    document_services.add_document_to_set_version(
        set_version=candidate, document_version=version, actor="operator"
    )
    schedule = configure_sync_schedule(
        actor=author,
        source=source,
        interval_seconds=900,
        enabled=True,
        next_run_at=timezone.now(),
    )
    assert claim_connector_automation(
        schedule_id=schedule.pk,
        candidate_set_version_id=candidate.pk,
        organization_id=organization.pk,
    )
    with pytest.raises(ConnectorAutomationError, match="AUTOMATION_ALREADY_RUNNING"):
        claim_connector_automation(
            schedule_id=schedule.pk,
            candidate_set_version_id=candidate.pk,
            organization_id=organization.pk,
        )

    schedule.__class__.objects.filter(pk=schedule.pk).update(
        updated_at=timezone.now() - timedelta(minutes=36)
    )
    assert claim_connector_automation(
        schedule_id=schedule.pk,
        candidate_set_version_id=candidate.pk,
        organization_id=organization.pk,
    )


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_generic_rest_lineage_and_schedule_rls_are_forced_and_fail_closed(
    governed_rest: Any,
) -> None:
    _, author, organization, _, source = governed_rest
    create_rest_sync_run(actor=author, source=source)
    configure_sync_schedule(
        actor=author,
        source=source,
        interval_seconds=900,
        enabled=False,
        next_run_at=timezone.now(),
    )
    role = f"rest_rls_probe_{uuid.uuid4().hex[:12]}"
    tables = (
        "ingestion_restpullcontract",
        "ingestion_tenantrestpullprofilegrant",
        "ingestion_restsyncrun",
        "ingestion_connectorsyncschedule",
    )
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOLOGIN')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        for table in tables:
            cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
        cursor.execute("SELECT set_config('app.tenant_scope', '', true)")
        cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
        for table in tables:
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
            assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")

        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(organization.id)])
        cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
        for table in tables:
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
            assert cursor.fetchone()[0] >= 1
        cursor.execute("RESET ROLE")

        for table in tables:
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                [table],
            )
            assert cursor.fetchone() == (True, True)
