"""Operator management commands: redacted listing and tenant-scoped cancellation."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.agents.models import AgentRunStatus
from apps.agents.tests.conftest import build_agent, make_run

pytestmark = pytest.mark.django_db


def test_list_agent_runs_outputs_redacted_summary() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    out = StringIO()
    call_command("list_agent_runs", "--organization", fixture.organization.slug, stdout=out)
    text = out.getvalue()
    assert str(run.public_id) in text
    assert "status=queued" in text
    # No raw objective/input leaks into operator output.
    assert "hello" not in text


def test_list_agent_runs_unknown_org_errors() -> None:
    with pytest.raises(CommandError):
        call_command("list_agent_runs", "--organization", "nope")


def test_cancel_agent_run_command() -> None:
    fixture = build_agent()
    run = make_run(fixture)
    out = StringIO()
    call_command(
        "cancel_agent_run",
        "--organization",
        fixture.organization.slug,
        "--run",
        str(run.public_id),
        "--actor",
        "operator-1",
        stdout=out,
    )
    run.refresh_from_db()
    assert run.status == AgentRunStatus.CANCELLED
    assert "status=cancelled" in out.getvalue()


def test_cancel_agent_run_rejects_cross_tenant() -> None:
    owner = build_agent(org_slug="owner-org")
    other = build_agent(org_slug="other-org")
    run = make_run(owner)
    with pytest.raises(CommandError):
        call_command(
            "cancel_agent_run",
            "--organization",
            other.organization.slug,
            "--run",
            str(run.public_id),
            "--actor",
            "operator-1",
        )
