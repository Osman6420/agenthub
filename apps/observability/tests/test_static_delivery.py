from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERIFIER = ROOT / "scripts" / "verify_static_assets.py"


def _run_verifier(
    static_root: Path,
    *,
    release_id: str = "release-123",
    manifest: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(VERIFIER),
        "--root",
        str(static_root),
        "--release-id",
        release_id,
    ]
    if manifest is not None:
        command.extend(["--manifest", str(manifest)])
    # The executable and script are repository-controlled; only temporary test paths are passed.
    return subprocess.run(  # noqa: S603
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_required_assets(static_root: Path) -> None:
    builder = static_root / "builder"
    builder.mkdir(parents=True)
    (builder / "builder.js").write_text("console.log('builder');\n", encoding="utf-8")
    (builder / "builder.css").write_text("body { color: #111; }\n", encoding="utf-8")


def test_static_asset_verifier_writes_bounded_checksum_manifest(tmp_path: Path) -> None:
    static_root = tmp_path / "staticfiles"
    _write_required_assets(static_root)
    (static_root / "admin").mkdir()
    (static_root / "admin" / "base.css").write_text("body {}\n", encoding="utf-8")
    manifest_path = static_root / "asset-manifest.json"

    result = _run_verifier(static_root, manifest=manifest_path)

    assert result.returncode == 0, result.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_id"] == "release-123"
    assert manifest["asset_count"] == 3
    assert [item["path"] for item in manifest["assets"]] == [
        "admin/base.css",
        "builder/builder.css",
        "builder/builder.js",
    ]
    assert all(len(item["sha256"]) == 64 and item["size"] > 0 for item in manifest["assets"])
    assert str(tmp_path) not in manifest_path.read_text(encoding="utf-8")


def test_static_asset_verifier_fails_closed_for_missing_or_forbidden_assets(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    missing = _run_verifier(missing_root)
    assert missing.returncode == 1
    assert "required static asset is missing or empty" in missing.stderr

    forbidden_root = tmp_path / "forbidden"
    _write_required_assets(forbidden_root)
    (forbidden_root / "builder" / "builder.js.map").write_text("{}", encoding="utf-8")
    forbidden = _run_verifier(forbidden_root)
    assert forbidden.returncode == 1
    assert "forbidden static artifact" in forbidden.stderr


def test_static_asset_verifier_rejects_unsafe_release_and_manifest_paths(
    tmp_path: Path,
) -> None:
    static_root = tmp_path / "staticfiles"
    _write_required_assets(static_root)

    unsafe_release = _run_verifier(static_root, release_id="../escape")
    assert unsafe_release.returncode == 1
    assert "release id must match" in unsafe_release.stderr

    outside_manifest = _run_verifier(static_root, manifest=tmp_path / "manifest.json")
    assert outside_manifest.returncode == 1
    assert "manifest must be inside static root" in outside_manifest.stderr


def _production_settings_process(
    *, static_release: str, static_url: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "AGENTHUB_IMAGE_RELEASE_ID": static_release,
            "AGENTHUB_STATIC_RELEASE_ID": static_release,
            "DJANGO_ALLOWED_HOSTS": "agenthub.example.invalid",
            "DJANGO_SECRET_KEY": "test-only-production-settings-secret",
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_STATIC_URL": static_url,
        }
    )
    code = """
import django
django.setup()
from django.conf import settings
from django.urls import Resolver404, resolve
assert settings.DEBUG is False
assert settings.STATIC_URL == "/static/release-123/"
try:
    resolve("/static/release-123/builder/builder.js")
except Resolver404:
    pass
else:
    raise AssertionError("production URLConf must not serve development static routes")
print("production static settings verified")
"""
    # The executable and inline probe are repository-controlled and transmit no external data.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_production_settings_require_matching_versioned_static_url() -> None:
    valid = _production_settings_process(
        static_release="release-123",
        static_url="/static/release-123/",
    )
    assert valid.returncode == 0, valid.stderr
    assert "production static settings verified" in valid.stdout

    mismatch = _production_settings_process(
        static_release="release-123",
        static_url="/static/other-release/",
    )
    assert mismatch.returncode != 0
    assert "DJANGO_STATIC_URL must equal" in mismatch.stderr

    image_mismatch_env = os.environ.copy()
    image_mismatch_env.update(
        {
            "AGENTHUB_IMAGE_RELEASE_ID": "wrong-image",
            "AGENTHUB_STATIC_RELEASE_ID": "release-123",
            "DJANGO_ALLOWED_HOSTS": "agenthub.example.invalid",
            "DJANGO_SECRET_KEY": "test-only-production-settings-secret",
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_STATIC_URL": "/static/release-123/",
        }
    )
    image_mismatch = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=ROOT,
        env=image_mismatch_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert image_mismatch.returncode != 0
    assert "AGENTHUB_IMAGE_RELEASE_ID must match" in image_mismatch.stderr


def test_static_container_contract_is_fail_closed_and_non_logging() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "static" / "nginx.conf").read_text(encoding="utf-8")

    assert "npm --prefix frontend ci" in dockerfile
    assert "python manage.py collectstatic --noinput --clear" in dockerfile
    assert "verify_static_assets.py" in dockerfile
    assert "COPY docs/architecture/workflow-dsl-llm-guide.md" in dockerfile
    assert 'ENV AGENTHUB_IMAGE_RELEASE_ID="${STATIC_RELEASE_ID}"' in dockerfile
    assert "ARG NGINX_BASE_IMAGE=nginxinc/nginx-unprivileged:1.28.1-alpine" in dockerfile
    assert "FROM ${NGINX_BASE_IMAGE} AS static-runtime" in dockerfile
    assert "USER 101" in dockerfile
    assert "$request_uri" not in nginx
    assert "$args" not in nginx
    assert "autoindex off;" in nginx
    assert "try_files $uri =404;" in nginx
    assert 'add_header Cache-Control "public, max-age=31536000, immutable" always;' in nginx
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx
    assert 'add_header Cross-Origin-Resource-Policy "same-origin" always;' in nginx


def test_standalone_static_dockerfile_preserves_canonical_static_contract() -> None:
    canonical = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    standalone = (ROOT / "deploy" / "static.Dockerfile").read_text(encoding="utf-8")
    shared_fragments = (
        "ARG NODE_BASE_IMAGE=node:20.20.0-bookworm-slim",
        "ARG PYTHON_BASE_IMAGE=python:3.13-slim",
        "ARG NGINX_BASE_IMAGE=nginxinc/nginx-unprivileged:1.28.1-alpine",
        "npm --prefix frontend run typecheck",
        "python manage.py collectstatic --noinput --clear",
        "--manifest /app/staticfiles/asset-manifest.json",
        "COPY deploy/static/nginx.conf /etc/nginx/nginx.conf",
        "USER 101",
    )
    for fragment in shared_fragments:
        assert fragment in canonical
        assert fragment in standalone


def test_production_health_probe_headers_avoid_host_rejection_and_https_redirect() -> None:
    env = os.environ.copy()
    env.update(
        {
            "AGENTHUB_IMAGE_RELEASE_ID": "release-123",
            "AGENTHUB_STATIC_RELEASE_ID": "release-123",
            "DJANGO_ALLOWED_HOSTS": "agenthub-web",
            "DJANGO_SECRET_KEY": "test-only-production-settings-secret",
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_STATIC_URL": "/static/release-123/",
        }
    )
    code = """
import django
django.setup()
from django.test import Client
response = Client().get(
    "/v1/health/live",
    HTTP_HOST="agenthub-web",
    HTTP_X_FORWARDED_PROTO="https",
)
assert response.status_code == 200, response.status_code
print("production health probe headers verified")
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "production health probe headers verified" in result.stdout
