from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection

from apps.audit.models import AuditEvent
from apps.documents import storage
from apps.documents.models import (
    Document,
    DocumentSet,
    DocumentSetStatus,
    DocumentSetVersionStatus,
)
from apps.documents.services import publish_document_set_version
from apps.identity.roles import Role
from apps.ingestion.confluence import (
    ConfluenceDataCenterClient,
    ConfluenceError,
    ConfluencePage,
)
from apps.ingestion.confluence_schema import (
    ConfluenceValidationError,
    canonicalize_confluence_base_url,
)
from apps.ingestion.confluence_services import (
    ConfluenceAuthorizationError,
    ConfluenceServiceError,
    create_confluence_source,
    create_confluence_sync_run,
    grant_confluence_profile,
    register_confluence_profile,
)
from apps.ingestion.confluence_sync import execute_confluence_sync
from apps.ingestion.models import (
    ConfluenceCursorState,
    ConfluenceDocumentCursor,
    ConfluenceSyncStatus,
)
from apps.tenancy.models import Organization, OrganizationMembership


class _SecretResolver:
    def resolve(self, ref: str) -> str:
        assert ref == "secret:kb-reader"
        return "pat-value"  # noqa: S105


class _Response:
    def __init__(self, status: int, payload: dict[str, Any] | bytes) -> None:
        self.status = status
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return "application/json; charset=utf-8" if name.lower() == "content-type" else default


class _Connection:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.requests.append((method, url, body, headers or {}))

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        pass


class _Factory:
    def __init__(self, *connections: _Connection) -> None:
        self.connections = list(connections)
        self.used: list[_Connection] = []

    def __call__(self, ip: str, port: int, timeout: float, hostname: str) -> _Connection:
        assert (ip, port, hostname) == ("10.20.30.40", 443, "confluence.corp.example")
        connection = self.connections.pop(0)
        self.used.append(connection)
        return connection


def _resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", ("10.20.30.40", port))]


def _page(page_id: str, version: int = 1, title: str = "Page") -> dict[str, Any]:
    return {
        "id": page_id,
        "type": "page",
        "status": "current",
        "title": title,
        "version": {"number": version, "when": "2026-07-13T12:00:00+03:00"},
    }


def _profile(**overrides: Any) -> Any:
    values = {
        "scheme": "https",
        "host": "confluence.corp.example",
        "port": 443,
        "context_path": "/confluence",
        "secret_ref": "secret:kb-reader",
        "network_policy_id": "corp-confluence",
        "timeout_seconds": 30,
        "page_size": 50,
        "max_pages": 100,
        "max_depth": 1,
        "max_requests": 100,
        "max_retries": 1,
        "max_response_bytes": 1_000_000,
        "max_page_body_bytes": 500_000,
        "max_total_bytes": 2_000_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(factory: _Factory, sleeper=lambda seconds: None) -> ConfluenceDataCenterClient:
    return ConfluenceDataCenterClient(
        resolver=_resolver,
        connection_factory=factory,
        secret_resolver=_SecretResolver(),
        network_policies={"corp-confluence": ["10.20.30.0/24"]},
        sleeper=sleeper,
    )


def test_client_bfs_uses_fixed_paths_and_ignores_response_links() -> None:
    root = _Connection(_Response(200, _page("100", title="Root")))
    children = _Connection(
        _Response(
            200,
            {
                "results": [_page("101", title="A"), _page("102", title="B")],
                "size": 2,
                "_links": {"next": "https://attacker.example/internal"},
            },
        )
    )
    body_payload = _page("101", version=2, title="A2")
    body_payload["body"] = {"storage": {"value": "<p>Safe text</p>"}}
    body = _Connection(_Response(200, body_payload))
    factory = _Factory(root, children, body)
    client = _client(factory)

    pages = list(
        client.iter_pages(
            _profile(),
            root_page_ids=["100"],
            include_root=True,
            excluded_page_ids=set(),
        )
    )
    assert [page.page_id for page in pages] == ["100", "101", "102"]
    returned, content = client.get_page_body(_profile(), "101", "100")
    assert returned.version == 2 and content == b"<p>Safe text</p>"
    paths = [connection.requests[0][1] for connection in factory.used]
    assert paths == [
        "/confluence/rest/api/content/100?expand=version",
        "/confluence/rest/api/content/100/child/page?start=0&limit=50&expand=version",
        "/confluence/rest/api/content/101?expand=body.storage%2Cversion",
    ]
    assert all("attacker.example" not in path for path in paths)
    assert factory.used[0].requests[0][3]["Authorization"] == "Bearer pat-value"


def test_client_retries_get_503_but_rejects_page_id_mismatch() -> None:
    unavailable = _Connection(_Response(503, b"temporary"))
    mismatched = _Connection(_Response(200, _page("999")))
    sleeps: list[float] = []
    client = _client(_Factory(unavailable, mismatched), sleeps.append)

    with pytest.raises(ConfluenceError, match="CONFLUENCE_PAGE_ID_MISMATCH"):
        list(
            client.iter_pages(
                _profile(),
                root_page_ids=["100"],
                include_root=True,
                excluded_page_ids=set(),
            )
        )
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    "value",
    [
        "http://confluence.corp.example",
        "https://user:pass@confluence.corp.example",
        "https://confluence.corp.example/confluence?next=x",
        "https://confluence.corp.example/%2e%2e/admin",
    ],
)
def test_base_url_canonicalization_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ConfluenceValidationError):
        canonicalize_confluence_base_url(value)


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    settings.CONFLUENCE_NETWORK_POLICIES = {"corp-confluence": ["10.20.30.0/24"]}
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


@pytest.fixture
def governed_source(db: Any) -> tuple[Any, Organization, DocumentSet, Any, Any]:
    organization = Organization.objects.create(slug="conf", name="Confluence")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="kb", name="Knowledge Base"
    )
    platform = get_user_model().objects.create_superuser(username="platform", password=None)
    author = get_user_model().objects.create_user(username="author")
    OrganizationMembership.objects.create(
        organization=organization, user=author, role=Role.SCENARIO_EDITOR
    )
    profile = register_confluence_profile(
        actor=platform,
        base_url="https://confluence.corp.example/confluence/",
        logical_id="corp-kb",
        revision=1,
        secret_ref="secret:kb-reader",  # noqa: S106
        network_policy_id="corp-confluence",
        timeout_seconds=30,
        page_size=50,
        max_pages=100,
        max_depth=10,
        max_requests=500,
        max_retries=1,
        max_response_bytes=1_000_000,
        max_page_body_bytes=500_000,
        max_total_bytes=5_000_000,
    )
    grant_confluence_profile(
        actor=platform,
        organization=organization,
        document_set=document_set,
        confluence_profile=profile,
    )
    source = create_confluence_source(
        actor=author,
        organization=organization,
        document_set=document_set,
        confluence_profile=profile,
        slug="kb-source",
        name="KB Source",
        connector_config={"root_page_ids": ["100"], "include_root": True},
    )
    return platform, organization, document_set, author, source


def test_profile_and_source_governance_redacts_endpoint_and_denies_inline_url(
    governed_source: tuple[Any, Organization, DocumentSet, Any, Any],
) -> None:
    _platform, organization, document_set, author, source = governed_source
    event = AuditEvent.objects.get(action="confluence_profile.create")
    serialized = f"{event.after}{event.reason}"
    assert "confluence.corp.example" not in serialized
    assert "10.20.30" not in serialized
    assert "kb-reader" not in serialized
    assert source.connector_config == {
        "root_page_ids": ["100"],
        "include_root": True,
        "excluded_page_ids": [],
    }
    with pytest.raises(ConfluenceValidationError, match="SOURCE_CONFIG_INVALID"):
        create_confluence_source(
            actor=author,
            organization=organization,
            document_set=document_set,
            confluence_profile=source.confluence_profile,
            slug="bad",
            name="Bad",
            connector_config={
                "root_page_ids": ["100"],
                "base_url": "https://attacker.example",
            },
        )
    ungranted_set = DocumentSet.objects.create(
        organization=organization, logical_id="other-kb", name="Other KB"
    )
    with pytest.raises(ConfluenceAuthorizationError, match="PROFILE_NOT_GRANTED"):
        create_confluence_source(
            actor=author,
            organization=organization,
            document_set=ungranted_set,
            confluence_profile=source.confluence_profile,
            slug="ungranted",
            name="Ungranted",
            connector_config={"root_page_ids": ["100"]},
        )
    assert AuditEvent.objects.filter(
        action="confluence_source.create",
        outcome="deny",
        reason="CONFLUENCE_PROFILE_NOT_GRANTED",
    ).exists()
    source.document_set = ungranted_set
    with pytest.raises(ValueError, match="binding is immutable"):
        source.save()


def test_quarantined_set_rejects_new_confluence_sync(governed_source: Any) -> None:
    _platform, _organization, document_set, author, source = governed_source
    document_set.status = DocumentSetStatus.QUARANTINED
    document_set.save(update_fields=["status", "updated_at"])

    with pytest.raises(ConfluenceServiceError, match="DOCUMENT_SET_QUARANTINED"):
        create_confluence_sync_run(actor=author, source=source)


def test_non_platform_cannot_register_profile(settings: Any, db: Any) -> None:
    user = get_user_model().objects.create_user(username="ordinary")
    with pytest.raises(ConfluenceAuthorizationError, match="PLATFORM_ADMIN_REQUIRED"):
        register_confluence_profile(
            actor=user,
            base_url="https://confluence.corp.example/confluence",
            logical_id="denied",
            revision=1,
            secret_ref="secret:kb-reader",  # noqa: S106
            network_policy_id="corp-confluence",
            timeout_seconds=30,
            page_size=50,
            max_pages=100,
            max_depth=10,
            max_requests=500,
            max_retries=1,
            max_response_bytes=1_000_000,
            max_page_body_bytes=500_000,
            max_total_bytes=5_000_000,
        )
    assert AuditEvent.objects.filter(action="confluence_profile.create", outcome="deny").exists()


class _SyncClient:
    def __init__(
        self,
        pages: list[ConfluencePage],
        bodies: dict[str, tuple[ConfluencePage, bytes]],
        *,
        fail_after: int | None = None,
    ) -> None:
        self.pages = pages
        self.bodies = bodies
        self.fail_after = fail_after
        self.body_calls: list[str] = []
        self.fetched_bytes = 0

    def iter_pages(self, profile: Any, **kwargs: Any) -> Iterator[ConfluencePage]:
        for index, page in enumerate(self.pages):
            if self.fail_after is not None and index >= self.fail_after:
                raise ConfluenceError("CONFLUENCE_UPSTREAM_UNAVAILABLE")
            yield page

    def get_page_body(
        self, profile: Any, page_id: str, root_page_id: str
    ) -> tuple[ConfluencePage, bytes]:
        self.body_calls.append(page_id)
        page, body = self.bodies[page_id]
        self.fetched_bytes += len(body)
        return page, body


def _sync_page(page_id: str, version: int, title: str) -> ConfluencePage:
    return ConfluencePage(
        page_id=page_id,
        title=title,
        version=version,
        updated_at=None,
        root_page_id="100",
    )


@pytest.mark.django_db
def test_sync_is_incremental_reconciles_only_complete_snapshot_and_creates_drafts(
    governed_source: tuple[Any, Organization, DocumentSet, Any, Any],
) -> None:
    _platform, _organization, document_set, author, source = governed_source
    root_v1 = _sync_page("100", 1, "Root")
    child_v1 = _sync_page("101", 1, "Child")
    first_client = _SyncClient(
        [root_v1, child_v1],
        {
            "100": (root_v1, b"<p>Root one</p>"),
            "101": (child_v1, b"<p>Child one</p>"),
        },
    )
    first = create_confluence_sync_run(actor=author, source=source)
    assert (
        execute_confluence_sync(
            first.pk, organization_id=source.organization_id, client=first_client
        )
        == ConfluenceSyncStatus.SUCCEEDED
    )
    first.refresh_from_db()
    assert first.snapshot_complete and first.changed_count == 2
    assert first.candidate_set_version is not None
    assert first.candidate_set_version.status == DocumentSetVersionStatus.DRAFT
    assert first.candidate_set_version.memberships.count() == 2
    published = publish_document_set_version(
        set_version=first.candidate_set_version, actor="operator"
    )

    second_client = _SyncClient([root_v1, child_v1], {})
    second = create_confluence_sync_run(actor=author, source=source)
    assert (
        execute_confluence_sync(
            second.pk, organization_id=source.organization_id, client=second_client
        )
        == ConfluenceSyncStatus.SUCCEEDED
    )
    second.refresh_from_db()
    assert second.unchanged_count == 2 and second.changed_count == 0
    assert second_client.body_calls == []

    root_v2 = _sync_page("100", 2, "Root changed")
    third_client = _SyncClient([root_v2], {"100": (root_v2, b"<p>Root two</p>")})
    third = create_confluence_sync_run(actor=author, source=source)
    assert (
        execute_confluence_sync(
            third.pk, organization_id=source.organization_id, client=third_client
        )
        == ConfluenceSyncStatus.SUCCEEDED
    )
    third.refresh_from_db()
    assert third.changed_count == 1 and third.missing_count == 1
    assert third.candidate_set_version is not None
    assert third.candidate_set_version.memberships.count() == 1
    assert ConfluenceDocumentCursor.objects.get(external_page_id="101").state == "missing"
    assert Document.objects.get(logical_id=f"confluence-{source.pk}-100").current_version == 2
    published.refresh_from_db()
    assert published.status == DocumentSetVersionStatus.PROMOTABLE
    assert published.memberships.count() == 2

    root_v3 = _sync_page("100", 3, "Root partial")
    partial_client = _SyncClient(
        [root_v3, child_v1],
        {"100": (root_v3, b"<p>Root three</p>")},
        fail_after=1,
    )
    partial = create_confluence_sync_run(actor=author, source=source, max_attempts=1)
    candidate_count = document_set.versions.count()
    assert (
        execute_confluence_sync(
            partial.pk, organization_id=source.organization_id, client=partial_client
        )
        == ConfluenceSyncStatus.DEAD_LETTER
    )
    partial.refresh_from_db()
    assert not partial.snapshot_complete and partial.candidate_set_version is None
    assert document_set.versions.count() == candidate_count
    assert ConfluenceDocumentCursor.objects.get(external_page_id="101").state == (
        ConfluenceCursorState.MISSING
    )


@pytest.mark.django_db
def test_sync_worker_tenant_context_cannot_claim_foreign_run(
    governed_source: tuple[Any, Organization, DocumentSet, Any, Any],
) -> None:
    _platform, _organization, _document_set, author, source = governed_source
    other = Organization.objects.create(slug="foreign", name="Foreign")
    run = create_confluence_sync_run(actor=author, source=source)
    client = _SyncClient([], {})

    assert execute_confluence_sync(run.pk, organization_id=other.id, client=client) == "not_claimed"
    run.refresh_from_db()
    assert run.status == ConfluenceSyncStatus.QUEUED and run.attempt == 0


@pytest.mark.django_db
def test_sync_run_rejects_attempt_budget_beyond_task_delivery_limit(
    governed_source: tuple[Any, Organization, DocumentSet, Any, Any],
) -> None:
    _platform, _organization, _document_set, author, source = governed_source

    with pytest.raises(ValidationError, match="must be between 1 and 3"):
        create_confluence_sync_run(actor=author, source=source, max_attempts=4)


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_confluence_lineage_rls_is_forced_and_fail_closed(
    governed_source: tuple[Any, Organization, DocumentSet, Any, Any],
) -> None:
    _platform, organization, _document_set, author, source = governed_source
    run = create_confluence_sync_run(actor=author, source=source)
    role = f"confluence_rls_probe_{run.pk}"
    table = "ingestion_confluencesyncrun"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute("SELECT set_config('app.tenant_scope', '', true)")
        cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")

        cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [str(organization.id)])
        cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")

        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", [table]
        )
        assert cursor.fetchone() == (True, True)
