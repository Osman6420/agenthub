from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _documents(name: str) -> list[dict]:
    path = ROOT / "deploy" / "openshift" / name
    return [item for item in yaml.safe_load_all(path.read_text(encoding="utf-8")) if item]


def test_only_web_has_external_route_and_all_workloads_are_restricted() -> None:
    documents = _documents("platform.yaml")
    routes = [item for item in documents if item["kind"] == "Route"]
    assert len(routes) == 1
    assert routes[0]["spec"]["to"]["name"] == "agenthub-web"

    deployments = [item for item in documents if item["kind"] == "Deployment"]
    assert {item["metadata"]["name"] for item in deployments} == {
        "agenthub-web",
        "agenthub-worker-runtime",
        "agenthub-worker-ingestion",
        "agenthub-worker-eval",
        "agenthub-beat",
    }
    for deployment in deployments:
        pod = deployment["spec"]["template"]["spec"]
        assert pod["serviceAccountName"] != "default"
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in pod["containers"]:
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert security["readOnlyRootFilesystem"] is True
            assert security["runAsNonRoot"] is True
            assert security["capabilities"]["drop"] == ["ALL"]

    config = next(item for item in documents if item["kind"] == "ConfigMap")
    assert config["data"]["MCP_ENABLED"] == "false"


def test_network_policy_is_default_deny_without_catch_all_egress() -> None:
    policies = _documents("network-policies.yaml")
    default_deny = next(
        item for item in policies if item["metadata"]["name"] == "agenthub-default-deny"
    )
    assert default_deny["spec"]["podSelector"] == {}
    assert set(default_deny["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert "egress" not in default_deny["spec"]

    for policy in policies:
        for rule in policy["spec"].get("egress", []):
            assert rule.get("to")


def test_secret_template_contains_references_not_values() -> None:
    text = (ROOT / "deploy" / "openshift" / "external-secrets.example.yaml").read_text(
        encoding="utf-8"
    )
    documents = list(yaml.safe_load_all(text))
    assert {item["kind"] for item in documents} == {"ExternalSecret"}
    assert "stringData:" not in text
    assert "dataFrom:" not in text


def test_alerts_and_dashboard_have_actionable_content() -> None:
    rules = list(
        yaml.safe_load_all(
            (ROOT / "deploy" / "monitoring" / "prometheus-rules.yaml").read_text(encoding="utf-8")
        )
    )[0]
    alerts = rules["groups"][0]["rules"]
    assert alerts
    assert all(rule["annotations"].get("runbook_url") for rule in alerts)

    dashboard = json.loads(
        (ROOT / "deploy" / "monitoring" / "grafana-dashboard.json").read_text(encoding="utf-8")
    )
    assert len(dashboard["panels"]) >= 4
