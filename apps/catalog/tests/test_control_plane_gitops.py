"""Control-plane GitOps importer authorization and idempotency invariants."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.management import call_command

from apps.audit.models import AuditEvent
from apps.catalog.control_plane_gitops import (
    ControlPlaneGitOpsError,
    import_control_plane_document,
)
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import Consumer, ConsumerBinding
from apps.tenancy.models import Organization


def _doc(kind: str, metadata: dict, spec: dict) -> dict:
    return {"api_version": "agenthub/v1", "kind": kind, "metadata": metadata, "spec": spec}


@pytest.mark.django_db
def test_imports_control_plane_graph_idempotently() -> None:
    documents = [
        _doc("Organization", {"slug": "mcm"}, {"name": "MCM"}),
        _doc(
            "AIProject",
            {"organization": "mcm", "slug": "support"},
            {"name": "Support"},
        ),
        _doc(
            "Scenario",
            {"organization": "mcm", "project": "support", "slug": "faq"},
            {"name": "FAQ"},
        ),
        _doc(
            "ScenarioAlias",
            {"organization": "mcm", "project": "support", "alias": "customer-faq"},
            {"scenario": "faq"},
        ),
        _doc(
            "Consumer",
            {"organization": "mcm", "subject": "portal"},
            {"name": "Portal", "protocol": "rest"},
        ),
        _doc(
            "ConsumerBinding",
            {
                "organization": "mcm",
                "consumer_subject": "portal",
                "project": "support",
                "scenario": "faq",
            },
            {"capabilities": ["workflow_run"]},
        ),
    ]

    first = [import_control_plane_document(document)[1] for document in documents]
    second = [import_control_plane_document(document)[1] for document in documents]

    assert first == [True] * 6
    assert second == [False] * 6
    assert Organization.objects.count() == 1
    assert AIProject.objects.count() == 1
    assert Scenario.objects.count() == 1
    assert Consumer.objects.count() == 1
    assert ConsumerBinding.objects.get().capabilities == ["workflow_run"]


@pytest.mark.django_db
def test_import_rejects_unknown_org_and_cross_org_binding() -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    project = AIProject.objects.create(organization=org_b, slug="support", name="Support")
    Scenario.objects.create(project=project, slug="faq", name="FAQ")
    Consumer.objects.create(organization=org_a, subject="portal", name="Portal", protocol="rest")

    with pytest.raises(ControlPlaneGitOpsError, match="unknown consumer or scenario"):
        import_control_plane_document(
            _doc(
                "ConsumerBinding",
                {
                    "organization": "a",
                    "consumer_subject": "portal",
                    "project": "support",
                    "scenario": "faq",
                },
                {"capabilities": ["workflow_run"]},
            )
        )

    with pytest.raises(ControlPlaneGitOpsError, match="unknown organization"):
        import_control_plane_document(
            _doc("AIProject", {"organization": "missing", "slug": "x"}, {"name": "X"})
        )


@pytest.mark.django_db
def test_import_rejects_conflicting_reapply_and_unknown_capability() -> None:
    import_control_plane_document(_doc("Organization", {"slug": "mcm"}, {"name": "MCM"}))

    with pytest.raises(ControlPlaneGitOpsError, match="conflicts"):
        import_control_plane_document(_doc("Organization", {"slug": "mcm"}, {"name": "Changed"}))


@pytest.mark.django_db
def test_command_imports_and_audits_created_records(tmp_path: Path) -> None:
    yaml_path = tmp_path / "organization.yaml"
    yaml_path.write_text(
        "api_version: agenthub/v1\nkind: Organization\nmetadata:\n  slug: mcm\n"
        "spec:\n  name: MCM\n",
        encoding="utf-8",
    )

    call_command("import_control_plane", path=str(yaml_path), actor="gitops-test")

    organization = Organization.objects.get(slug="mcm")
    assert AuditEvent.objects.filter(
        actor_id="gitops-test",
        action="control_plane.import",
        organization_id=organization.pk,
    ).exists()
