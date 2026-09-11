"""Connection checks exercise real profile/grant/audit boundaries, fake external I/O."""

import time
from threading import Event
from typing import cast

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.ingestion.models import TenantRestPullProfileGrant
from apps.ingestion.rest import GovernedRestClient, RestPullError
from apps.ingestion.rest_probe import probe_rest_connection
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.tests.test_rest_pull import (
    _Connection,
    _definition,
    _Factory,
    _profile,
    _resolver,
    _Response,
    _Secrets,
)
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tools.deadline_dns import bounded_resolver
from apps.tools.egress import EgressDenied
from apps.tools.http_adapter import ConnectionFactory


def test_first_page_uses_identical_pagination_and_path_without_followup():
    payload: dict[str, object] = {"data": {"items": []}}
    response = _Connection(_Response(200, payload))
    definition = _definition()
    definition["pagination"] = {"mode": "page_number", "parameter": "page", "page_size": 10}
    client = GovernedRestClient(
        resolver=_resolver,
        connection_factory=cast(ConnectionFactory, _Factory(response)),
        secret_resolver=_Secrets(),
    )
    assert client.read_first_page(_profile(), definition, inputs={"dataset": "a/b"}) == payload
    assert len(response.requests) == 1
    assert response.requests[0][1] == "/api/v1/datasets/a%2Fb/documents?include=content&page=1"


def test_expired_deadline_prevents_dns_and_secret_resolution():
    def unreachable(*args):
        pytest.fail("Egress cannot begin after deadline")

    client = GovernedRestClient(resolver=unreachable, deadline=time.monotonic() - 1)
    with pytest.raises(RestPullError, match="DEADLINE"):
        client.read_first_page(_profile(), _definition(), inputs={"dataset": "kb"})


def test_bounded_dns_retains_capacity_until_timed_out_lookup_really_finishes(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import BoundedSemaphore

    import apps.tools.deadline_dns as module

    stop = Event()
    entered = Event()

    def slow(host, port):
        entered.set()
        stop.wait()
        return _resolver(host, port)

    pool = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(module, "_POOL", pool)
    monkeypatch.setattr(module, "_SLOTS", BoundedSemaphore(1))
    try:
        with pytest.raises(EgressDenied, match="DEADLINE"):
            bounded_resolver(time.monotonic() + 0.05, slow)("api.example.com", 443)
        assert entered.is_set()
        with pytest.raises(EgressDenied, match="CAPACITY"):
            bounded_resolver(time.monotonic() + 1, _resolver)("api.example.com", 443)
    finally:
        stop.set()
        pool.shutdown(wait=True)


def args(setup):
    return {
        "actor": setup[1],
        "organization_id": setup[2].pk,
        "document_set_id": setup[3].pk,
        "profile_id": setup[4].rest_profile.public_id,
        "definition": _definition(),
        "inputs": {"dataset": "protected-input"},
    }


def wire(monkeypatch, *, response=None, resolver=_resolver, fail_request=False):
    import apps.ingestion.rest_probe as module

    payload = {
        "data": {
            "items": [
                {
                    "id": "private-id",
                    "revision": "v1",
                    "title": "private-title",
                    "content": "private-content",
                }
            ]
        }
    }
    upstream = response or _Connection(_Response(200, payload), uncertain=fail_request)

    def factory(**kwargs):
        assert not connection.in_atomic_block
        kwargs["resolver"] = bounded_resolver(kwargs["deadline"], resolver)
        return GovernedRestClient(
            **kwargs,
            connection_factory=cast(ConnectionFactory, _Factory(upstream)),
            secret_resolver=_Secrets(),
        )

    monkeypatch.setattr(module, "GovernedRestClient", factory)
    return upstream


@pytest.mark.django_db(transaction=True)
def test_probe_has_committed_audit_bounded_io_redacted_result_and_cooldown(
    governed_rest, monkeypatch
):
    upstream = wire(monkeypatch)
    original_request = upstream.request

    def request(*args, **kwargs):
        assert not connection.in_atomic_block
        assert AuditEvent.objects.filter(action="rest_source.connection_test_started").exists()
        return original_request(*args, **kwargs)

    monkeypatch.setattr(upstream, "request", request)
    result = probe_rest_connection(**args(governed_rest))
    assert result.mapped_count == 1 and result.fetched_bytes > 0
    assert len(upstream.requests) == 1
    evidence = list(
        AuditEvent.objects.filter(action__startswith="rest_source.connection_test").values(
            "after", "reason"
        )
    )
    assert "private-" not in str(result) + str(evidence)
    assert "protected-input" not in str(evidence)
    with pytest.raises(RestServiceError, match="RATE_LIMITED"):
        probe_rest_connection(**args(governed_rest))


@pytest.mark.django_db(transaction=True)
def test_probe_rechecks_revocation_after_response_and_never_reports_success(
    governed_rest, monkeypatch
):
    upstream = wire(monkeypatch)
    original_request = upstream.request

    def request(*args, **kwargs):
        with transaction.atomic():
            TenantRestPullProfileGrant.objects.all().delete()
        return original_request(*args, **kwargs)

    monkeypatch.setattr(upstream, "request", request)
    with pytest.raises(RestAuthorizationError):
        probe_rest_connection(**args(governed_rest))
    assert not AuditEvent.objects.filter(
        action="rest_source.connection_test", outcome="success"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_probe_private_dns_and_unknown_response_never_retry(governed_rest, monkeypatch):
    upstream = wire(monkeypatch, resolver=lambda host, port: [(2, 1, 6, "", ("127.0.0.1", port))])
    with pytest.raises(RestPullError):
        probe_rest_connection(**args(governed_rest))
    assert not upstream.requests


@pytest.mark.django_db(transaction=True)
def test_probe_unknown_transport_has_one_attempt(governed_rest, monkeypatch):
    upstream = wire(monkeypatch, fail_request=True)
    with pytest.raises(RestPullError, match="UPSTREAM_UNAVAILABLE"):
        probe_rest_connection(**args(governed_rest))
    assert len(upstream.requests) == 1


@pytest.mark.django_db
def test_probe_refuses_outer_transaction(governed_rest):
    with pytest.raises(RestServiceError, match="COMMITTED_BOUNDARY"):
        probe_rest_connection(**args(governed_rest))
