"""Operator console agent-run views: login required, tenant-scoped, redacted trace."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.agents.models import AgentRun, AgentRunStatus
from apps.agents.tasks import execute_agent_run
from apps.agents.tests.conftest import build_agent, make_run
from apps.identity.roles import Role
from apps.tenancy.models import OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(client: Client, org, *, username: str = "op") -> None:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=Role.PROJECT_OWNER)
    client.force_login(user)


def test_agent_runs_list_requires_login() -> None:
    response = Client().get(reverse("console:agent_runs"))
    assert response.status_code == 302
    assert "/console/login/" in response["Location"]


def test_agent_runs_list_is_tenant_scoped() -> None:
    owner = build_agent(org_slug="owner-org")
    other = build_agent(org_slug="other-org")
    make_run(owner)
    make_run(other)
    client = Client()
    _member(client, owner.organization)
    body = client.get(reverse("console:agent_runs")).content.decode()
    assert "assistant" in body  # owner's scenario visible
    # Only the owner org's run id is shown; the other tenant's is not.
    other_run = AgentRun.objects.get(release=other.release)
    assert str(other_run.public_id)[:8] not in body


def test_agent_run_detail_shows_redacted_trace() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    execute_agent_run(run.id)
    client = Client()
    _member(client, fixture.organization)
    response = client.get(reverse("console:agent_run_detail", args=[str(run.public_id)]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Trace" in body
    assert "run_completed" in body
    # The raw objective must never appear in the trace view.
    assert "hello" not in body


def test_agent_run_detail_cross_tenant_denied() -> None:
    owner = build_agent(org_slug="owner-org")
    other = build_agent(org_slug="other-org")
    run = make_run(owner)
    client = Client()
    _member(client, other.organization)
    response = client.get(reverse("console:agent_run_detail", args=[str(run.public_id)]))
    assert response.status_code == 403


def test_console_cancel_agent_run() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    client = Client()
    _member(client, fixture.organization)
    response = client.post(reverse("console:agent_run_cancel", args=[str(run.public_id)]))
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.status == AgentRunStatus.CANCELLED
