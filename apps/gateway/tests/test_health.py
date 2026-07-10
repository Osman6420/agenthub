"""Tests for the operational health probes.

Dependency access is faked so the suite needs no external services (SQLite +
LocMem cache per the test settings). This covers: liveness, readiness happy
path, readiness failure (503), and the non-leak contract of the response body.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.gateway import health


@pytest.fixture
def client() -> Client:
    return Client()


def test_live_returns_ok(client: Client) -> None:
    response = client.get(reverse("gateway:health-live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_all_healthy(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    # Database is the real (SQLite) test DB; fake Redis as reachable.
    monkeypatch.setattr(health, "_check_redis", lambda: True)

    response = client.get(reverse("gateway:health-ready"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


@pytest.mark.django_db
def test_ready_returns_503_when_dependency_down(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "_check_redis", lambda: False)

    response = client.get(reverse("gateway:health-ready"))

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "error"


@pytest.mark.django_db
def test_ready_does_not_leak_sensitive_detail(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even on failure, the body must contain only coarse status keys/values.
    monkeypatch.setattr(health, "_check_redis", lambda: False)

    response = client.get(reverse("gateway:health-ready"))

    body = response.json()
    assert set(body.keys()) == {"status", "checks"}
    assert set(body["checks"].keys()) == {"database", "redis"}
    assert set(body["checks"].values()) <= {"ok", "error"}
