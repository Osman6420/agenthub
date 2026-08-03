from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def _server_module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "examples" / "external-consumer-demo" / "server.py"
    spec = importlib.util.spec_from_file_location("external_consumer_demo_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _credentials(path: Path, api_base: str) -> Path:
    path.write_text(
        json.dumps({"api_base": api_base, "consumers": {"research": {"token": "local"}}}),
        encoding="utf-8",
    )
    return path


def test_cluster_upstream_requires_explicit_startup_permission(tmp_path: Path) -> None:
    server = _server_module()
    path = _credentials(tmp_path / "credentials.json", "http://agenthub-web:8000")

    with pytest.raises(ValueError, match="explicitly allowed"):
        server.load_credentials(path)

    loaded = server.load_credentials(path, allow_cluster_upstream=True)
    assert loaded["_upstream_host"] == "agenthub-web"
    assert loaded["_upstream_port"] == 8000


@pytest.mark.parametrize(
    "api_base",
    [
        "http://10.0.0.7:8000",
        "https://agenthub-web:8000",
        "http://user:password@agenthub-web:8000",
        "http://agenthub-web:8000/console",
    ],
)
def test_cluster_upstream_rejects_unsafe_shapes(tmp_path: Path, api_base: str) -> None:
    server = _server_module()
    path = _credentials(tmp_path / "credentials.json", api_base)

    with pytest.raises(ValueError):
        server.load_credentials(path, allow_cluster_upstream=True)


def test_network_bind_requires_explicit_startup_permission() -> None:
    server = _server_module()

    assert server.validate_bind_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(ValueError, match="explicitly enabled"):
        server.validate_bind_host("0.0.0.0")  # noqa: S104 - explicit denial test
    assert (
        server.validate_bind_host(
            "0.0.0.0",  # noqa: S104 - explicit opt-in path under test
            allow_network_bind=True,
        )
        == "0.0.0.0"  # noqa: S104 - expected validated value
    )
