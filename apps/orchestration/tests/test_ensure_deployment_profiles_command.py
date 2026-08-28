from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ingestion.models import EmbeddingProfile
from apps.orchestration.models import ModelProfile, ModelProfileStatus


@pytest.fixture
def deployment_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "PLATFORM_ACTOR": "platform-recovery",
        "MODEL_LOGICAL_ID": "primary-chat",
        "MODEL_REVISION": "1",
        "MODEL_HOST": "models.example.com",
        "MODEL_PORT": "443",
        "MODEL_PATH": "/v1/chat/completions",
        "MODEL_NAME": "test-chat",
        "EMBEDDING_LOGICAL_ID": "primary-embedding",
        "EMBEDDING_REVISION": "1",
        "EMBEDDING_HOST": "embeddings.example.com",
        "EMBEDDING_PORT": "443",
        "EMBEDDING_PATH": "/v1/embeddings",
        "EMBEDDING_NAME": "test-embedding",
        "EMBEDDING_DIMENSIONS": "1024",
        "EMBEDDING_INDEX_TYPE": "vector",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.django_db
def test_ensure_deployment_profiles_creates_exact_profiles_idempotently(
    deployment_profile_env: None,
) -> None:
    get_user_model().objects.create_user(
        username="platform-recovery",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )

    call_command("ensure_deployment_profiles")
    call_command("ensure_deployment_profiles")
    call_command("ensure_deployment_profiles", check_only=True)

    model = ModelProfile.objects.get(logical_id="primary-chat", revision=1)
    assert model.host == "models.example.com"
    assert model.model == "test-chat"
    assert model.secret_ref == "secret:" + "primary"
    assert model.status == ModelProfileStatus.ACTIVE
    embedding = EmbeddingProfile.objects.get(logical_id="primary-embedding", revision=1)
    assert embedding.host == "embeddings.example.com"
    assert embedding.dimensions == 1024
    assert embedding.index_type == "vector"
    assert ModelProfile.objects.count() == 1
    assert EmbeddingProfile.objects.count() == 1


@pytest.mark.django_db
def test_check_only_distinguishes_missing_profiles_from_invalid_configuration(
    deployment_profile_env: None,
) -> None:
    with pytest.raises(CommandError) as missing:
        call_command("ensure_deployment_profiles", check_only=True)
    assert missing.value.returncode == 3
    assert "deployment profiles are missing" in str(missing.value)

    get_user_model().objects.create_user(
        username="platform-recovery",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    call_command("ensure_deployment_profiles")
    ModelProfile.objects.filter(logical_id="primary-chat", revision=1).update(
        status=ModelProfileStatus.DISABLED
    )

    with pytest.raises(CommandError) as mismatch:
        call_command("ensure_deployment_profiles", check_only=True)
    assert mismatch.value.returncode == 1
    assert "status" in str(mismatch.value)


@pytest.mark.django_db
def test_existing_profile_revision_must_match_declared_immutable_fields(
    deployment_profile_env: None,
) -> None:
    get_user_model().objects.create_user(
        username="platform-recovery",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    call_command("ensure_deployment_profiles")
    ModelProfile.objects.filter(logical_id="primary-chat", revision=1).update(model="other")

    with pytest.raises(CommandError) as mismatch:
        call_command("ensure_deployment_profiles", check_only=True)
    assert mismatch.value.returncode == 1
    assert "model" in str(mismatch.value)
    assert "other" not in str(mismatch.value)


@pytest.mark.django_db
def test_profile_creation_requires_platform_admin(
    deployment_profile_env: None,
) -> None:
    get_user_model().objects.create_user(
        username="platform-recovery",
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )

    with pytest.raises(CommandError) as denied:
        call_command("ensure_deployment_profiles")
    assert "PLATFORM_ADMIN_REQUIRED" in str(denied.value)
    assert ModelProfile.objects.count() == 0
    assert EmbeddingProfile.objects.count() == 0
