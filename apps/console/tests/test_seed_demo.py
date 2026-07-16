"""Smoke test for the local demo seeder (dev convenience command)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.catalog.models import Scenario
from apps.identity.models import Consumer, ConsumerProtocol
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_seed_demo_creates_a_complete_tenant() -> None:
    call_command("seed_demo", password="pw-demo-123", verbosity=0)  # noqa: S106

    org = Organization.objects.get(slug="demo")
    slugs = set(Scenario.objects.filter(project__organization=org).values_list("slug", flat=True))
    assert slugs == {"customer-information", "support-flow", "assistant"}

    # Every scenario has an active, promoted release.
    active = ScenarioRelease.objects.filter(
        scenario__project__organization=org, status=ReleaseStatus.ACTIVE
    ).count()
    assert active == 3

    consumer = Consumer.objects.get(organization=org, subject="demo-client")
    assert consumer.bindings.count() == 3
    assert consumer.tokens.count() == 1
    assert consumer.protocol == ConsumerProtocol.REST
    mcp_consumer = Consumer.objects.get(organization=org, subject="demo-mcp-client")
    assert mcp_consumer.protocol == ConsumerProtocol.MCP
    assert mcp_consumer.bindings.count() == 3
    assert mcp_consumer.tokens.count() == 1

    # One operator account per role exists and is scoped to the org.
    for username in ("admin", "editor", "releaser", "approver", "auditor"):
        assert User.objects.filter(username=username).exists()


def test_seed_demo_reset_is_idempotent() -> None:
    call_command("seed_demo", password="x", verbosity=0)  # noqa: S106
    call_command("seed_demo", password="x", reset=True, verbosity=0)  # noqa: S106
    assert Organization.objects.filter(slug="demo").count() == 1
    assert (
        ScenarioRelease.objects.filter(
            scenario__project__organization__slug="demo", status=ReleaseStatus.ACTIVE
        ).count()
        == 3
    )
