"""GitOps import validates and rejects inline secrets; export round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from apps.artifacts.gitops import API_VERSION, GitOpsError, artifact_to_document, import_document
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError
from apps.tenancy.models import Organization


@pytest.fixture
def org(db) -> Organization:
    return Organization.objects.create(slug="mcm", name="MCM")


@pytest.mark.django_db
def test_import_document_creates_artifact(org: Organization) -> None:
    doc = {
        "api_version": API_VERSION,
        "kind": "PolicyProfile",
        "metadata": {"organization": "mcm", "logical_id": "grounded"},
        "spec": {"grounding": {"required": True}},
    }
    artifact = import_document(doc, default_organization=None, created_by="cli")
    assert artifact.type == ArtifactType.POLICY_PROFILE
    assert artifact.ref == "grounded:v1"


@pytest.mark.django_db
def test_import_remains_compatible_with_previous_document_label(org: Organization) -> None:
    doc = {
        "api_version": "agenthub/v3",
        "kind": "PolicyProfile",
        "metadata": {"organization": "mcm", "logical_id": "legacy-label"},
        "spec": {"grounding": {"required": True}},
    }
    artifact = import_document(doc, default_organization=None, created_by="cli")
    assert artifact.ref == "legacy-label:v1"


@pytest.mark.django_db
def test_repository_gitops_examples_use_current_schema(org: Organization) -> None:
    paths = sorted(Path("gitops/mcm/artifacts").glob("*.yaml"))
    assert paths
    for path in paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc["api_version"] == API_VERSION
        import_document(doc, default_organization=org, created_by="test")


@pytest.mark.django_db
def test_import_rejects_inline_secret(org: Organization) -> None:
    doc = {
        "kind": "ModelProfile",
        "metadata": {"organization": "mcm", "logical_id": "chat"},
        "spec": {"token": "abc123"},
    }
    with pytest.raises(ArtifactValidationError, match="inline secret"):
        import_document(doc, default_organization=None, created_by="cli")


@pytest.mark.django_db
def test_import_rejects_unknown_kind(org: Organization) -> None:
    doc = {"kind": "Nope", "metadata": {"organization": "mcm", "logical_id": "x"}, "spec": {}}
    with pytest.raises(GitOpsError, match="unsupported kind"):
        import_document(doc, default_organization=None, created_by="cli")


@pytest.mark.django_db
def test_export_document_shape(org: Organization) -> None:
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.POLICY_PROFILE,
        logical_id="grounded",
        body={"grounding": {"required": True}},
        created_by="cli",
    )
    doc = artifact_to_document(artifact)
    assert doc["api_version"] == API_VERSION
    assert doc["kind"] == "PolicyProfile"
    assert doc["metadata"]["organization"] == "mcm"
    assert doc["metadata"]["version"] == 1
    assert doc["spec"] == {"grounding": {"required": True}}
