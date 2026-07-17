from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml
from django.test import override_settings

from apps.workflows.python_node_runner_service import _execute
from apps.workflows.python_nodes import OpenShiftPythonNodeRunner, PythonNodeError


class Response:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self, size: int) -> bytes:
        return self.body[:size]


def _arguments() -> dict[str, object]:
    return {
        "source": "def run(config, input): return {'value': input['value'] + 1}",
        "config": {},
        "input_payload": {"value": 2},
        "wall_seconds": 2.0,
        "memory_bytes": 64 * 1024 * 1024,
        "output_bytes": 1024,
        "idempotency_key": "wf:1:node:checksum",
        "requested_modules": frozenset(),
    }


@override_settings(
    PYTHON_NODE_RUNNER_URL="http://agenthub-python-runner:8080",
    PYTHON_NODE_RUNNER_ATTESTED=False,
)
def test_runner_requires_explicit_environment_attestation() -> None:
    runner = OpenShiftPythonNodeRunner()
    assert not runner.is_production_isolated
    with pytest.raises(PythonNodeError, match="PYTHON_NODE_RUNNER_NOT_ATTESTED"):
        runner.execute(**_arguments())  # type: ignore[arg-type]


@override_settings(
    PYTHON_NODE_RUNNER_URL="http://user:password@runner.invalid/path?redirect=yes",
    PYTHON_NODE_RUNNER_ATTESTED=True,
)
def test_runner_rejects_credentialed_or_pathful_endpoint() -> None:
    runner = OpenShiftPythonNodeRunner()
    assert runner.endpoint == ""
    with pytest.raises(PythonNodeError, match="PYTHON_NODE_RUNNER_NOT_ATTESTED"):
        runner.execute(**_arguments())  # type: ignore[arg-type]


@override_settings(
    PYTHON_NODE_RUNNER_URL="http://agenthub-python-runner:8080",
    PYTHON_NODE_RUNNER_ATTESTED=True,
)
def test_attested_runner_sends_bounded_protocol_and_returns_output() -> None:
    opener = Mock()
    opener.open.return_value = Response(
        {
            "status": "ok",
            "output": {"value": 3},
            "idempotency_checksum": hashlib.sha256(b"wf:1:node:checksum").hexdigest(),
        }
    )
    with patch("apps.workflows.python_nodes.urllib.request.build_opener", return_value=opener):
        output = OpenShiftPythonNodeRunner().execute(**_arguments())  # type: ignore[arg-type]
    assert output == {"value": 3}
    request = opener.open.call_args.args[0]
    body = json.loads(request.data)
    assert body["protocol_version"] == "python-node-runner/v1"
    assert body["idempotency_key"] == "wf:1:node:checksum"
    assert "environment" not in body


@override_settings(
    PYTHON_NODE_RUNNER_URL="http://agenthub-python-runner:8080",
    PYTHON_NODE_RUNNER_ATTESTED=True,
)
def test_capacity_and_transport_ambiguity_fail_closed() -> None:
    capacity = urllib.error.HTTPError("runner", 429, "busy", Message(), io.BytesIO(b""))
    capacity_opener = Mock()
    capacity_opener.open.side_effect = capacity
    with (
        patch(
            "apps.workflows.python_nodes.urllib.request.build_opener",
            return_value=capacity_opener,
        ),
        pytest.raises(PythonNodeError, match="PYTHON_NODE_RUNNER_CAPACITY"),
    ):
        OpenShiftPythonNodeRunner().execute(**_arguments())  # type: ignore[arg-type]
    unavailable_opener = Mock()
    unavailable_opener.open.side_effect = urllib.error.URLError("closed")
    with (
        patch(
            "apps.workflows.python_nodes.urllib.request.build_opener",
            return_value=unavailable_opener,
        ),
        pytest.raises(PythonNodeError, match="PYTHON_NODE_OUTCOME_UNKNOWN"),
    ):
        OpenShiftPythonNodeRunner().execute(**_arguments())  # type: ignore[arg-type]


def test_credentials_free_supervisor_executes_in_fresh_process() -> None:
    response = _execute(
        {
            "protocol_version": "python-node-runner/v1",
            "idempotency_key": "wf:1:node:checksum",
            "expires_at_unix_ms": int((time.time() + 5) * 1000),
            "source": "def run(config, input): return {'value': input['value'] + 1}",
            "config": {},
            "input": {"value": 2},
            "wall_milliseconds": 2000,
            "memory_bytes": 64 * 1024 * 1024,
            "output_bytes": 1024,
            "requested_modules": [],
        }
    )
    assert response == {
        "status": "ok",
        "output": {"value": 3},
        "idempotency_checksum": hashlib.sha256(b"wf:1:node:checksum").hexdigest(),
    }


def test_supervisor_revalidates_module_allowlist() -> None:
    with pytest.raises(ValueError, match="PYTHON_NODE_PROTOCOL_INVALID"):
        _execute(
            {
                "protocol_version": "python-node-runner/v1",
                "idempotency_key": "wf:1:node:checksum",
                "expires_at_unix_ms": int((time.time() + 5) * 1000),
                "source": "import os\ndef run(config, input): return {}",
                "config": {},
                "input": {},
                "wall_milliseconds": 2000,
                "memory_bytes": 64 * 1024 * 1024,
                "output_bytes": 1024,
                "requested_modules": ["os"],
            }
        )


def test_openshift_runner_manifest_has_fixed_pool_and_no_ambient_authority() -> None:
    root = Path(__file__).parents[3]
    documents = list(yaml.safe_load_all((root / "deploy/openshift/platform.yaml").read_text()))
    deployment = next(
        item
        for item in documents
        if item
        and item.get("kind") == "Deployment"
        and item["metadata"]["name"] == "agenthub-python-runner"
    )
    assert deployment["spec"]["replicas"] == 4
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    assert "envFrom" not in container
    assert "volumeMounts" not in container
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
    }
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"


def test_runner_has_no_dns_or_general_egress_policy() -> None:
    root = Path(__file__).parents[3]
    policies = list(
        yaml.safe_load_all((root / "deploy/openshift/network-policies.yaml").read_text())
    )
    dns = next(item for item in policies if item["metadata"]["name"] == "agenthub-allow-dns")
    expression = dns["spec"]["podSelector"]["matchExpressions"][0]
    assert expression == {
        "key": "app.kubernetes.io/name",
        "operator": "NotIn",
        "values": ["agenthub-python-runner"],
    }
    runner_policies = [
        item
        for item in policies
        if item
        and item["spec"].get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/name")
        == "agenthub-python-runner"
    ]
    assert all("Egress" not in item["spec"]["policyTypes"] for item in runner_policies)
