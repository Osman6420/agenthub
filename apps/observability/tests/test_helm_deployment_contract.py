from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_chart_versions_track_the_initialization_contract_change() -> None:
    agenthub = yaml.safe_load(
        (ROOT / "deploy/helm/agenthub/Chart.yaml").read_text(encoding="utf-8")
    )
    stack = yaml.safe_load(
        (ROOT / "deploy/helm/agenthub-stack/Chart.yaml").read_text(encoding="utf-8")
    )
    lock = yaml.safe_load(
        (ROOT / "deploy/helm/agenthub-stack/Chart.lock").read_text(encoding="utf-8")
    )
    assert agenthub["version"] == "0.2.0"
    assert stack["version"] == "0.2.0"
    assert stack["dependencies"][0]["version"] == "0.2.0"
    assert lock["dependencies"][0]["version"] == "0.2.0"


def test_database_initialization_values_are_closed_and_digest_pinned() -> None:
    schema = json.loads(
        (ROOT / "deploy/helm/agenthub/values.schema.json").read_text(encoding="utf-8")
    )
    assert "databaseInitialization" in schema["required"]
    database = schema["properties"]["databaseInitialization"]
    assert database["additionalProperties"] is False
    assert set(database["required"]) == {"mode", "timeoutSeconds", "probeImage"}
    assert database["properties"]["mode"]["enum"] == ["hooks", "jobs"]
    assert database["properties"]["probeImage"] == {"$ref": "#/definitions/image"}

    managed = yaml.safe_load(
        (ROOT / "deploy/helm/agenthub/values.openshift.example.yaml").read_text(encoding="utf-8")
    )
    bundled = yaml.safe_load(
        (ROOT / "deploy/helm/agenthub-stack/values.openshift.example.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert managed["databaseInitialization"]["mode"] == "hooks"
    assert bundled["agenthub"]["databaseInitialization"]["mode"] == "jobs"
    for image in (
        managed["databaseInitialization"]["probeImage"],
        bundled["agenthub"]["databaseInitialization"]["probeImage"],
    ):
        assert image["repository"]
        assert image["digest"].startswith("sha256:")
        assert len(image["digest"]) == 71


def test_helm_initialization_avoids_post_install_wait_cycle_and_fails_closed() -> None:
    hooks = (ROOT / "deploy/helm/agenthub/templates/hooks.yaml").read_text(encoding="utf-8")
    helpers = (ROOT / "deploy/helm/agenthub/templates/_helpers.tpl").read_text(encoding="utf-8")
    assert "post-install" not in hooks
    assert 'eq .Values.databaseInitialization.mode "hooks"' in hooks
    assert "pre-install,pre-upgrade" in hooks
    assert 'eq .Values.databaseInitialization.mode "jobs"' in hooks
    assert "-r{{ .Release.Revision }}" in hooks
    assert "python manage.py ensure_deployment_profiles" in hooks
    assert "MODEL_EXISTS" not in hooks
    assert "EMBEDDING_EXISTS" not in hooks
    assert "ensure_deployment_profiles --check-only" in helpers
    assert 'case "$status" in' in helpers
    assert "databaseProbeImage" in helpers


def test_web_probes_keep_http_semantics_with_allowlisted_virtual_host() -> None:
    deployments = (ROOT / "deploy/helm/agenthub/templates/deployments.yaml").read_text(
        encoding="utf-8"
    )
    assert "tcpSocket" not in deployments
    assert "path: /v1/health/ready" in deployments
    assert deployments.count("name: Host") == 3
    assert deployments.count("name: X-Forwarded-Proto") == 3
    assert 'printf "%s-web" (include "agenthub.fullname" .)' in deployments
    assert deployments.count("deploymentDatabaseGateInit") == 5


def test_binary_build_template_is_parameterized_and_triggerless() -> None:
    template = yaml.safe_load(
        (ROOT / "deploy/openshift/build/template.yaml").read_text(encoding="utf-8")
    )
    assert template["kind"] == "Template"
    assert {parameter["name"] for parameter in template["parameters"]} == {
        "RELEASE_ID",
        "NODE_BASE_IMAGE",
        "PYTHON_BASE_IMAGE",
        "NGINX_BASE_IMAGE",
        "PGVECTOR_BASE_IMAGE",
    }
    builds = [item for item in template["objects"] if item["kind"] == "BuildConfig"]
    streams = [item for item in template["objects"] if item["kind"] == "ImageStream"]
    assert len(builds) == 3
    assert len(streams) == 3
    for build in builds:
        assert build["spec"]["source"] == {"type": "Binary"}
        assert build["spec"]["triggers"] == []
        assert set(build["spec"]["resources"]) == {"requests", "limits"}
    assert not any("registry.mkk.com.tr" in str(item) for item in template["objects"])
