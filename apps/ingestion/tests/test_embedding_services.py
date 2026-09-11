"""EmbeddingProfile registration/grant: platform-admin authorization, audit, immutability."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent
from apps.ingestion.embedding_services import (
    EmbeddingProfileAuthorizationError,
    disable_embedding_profile,
    grant_embedding_profile,
    register_embedding_profile,
)
from apps.ingestion.models import EmbeddingProfile, TenantEmbeddingProfileGrant
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def _register(actor: Any) -> EmbeddingProfile:
    return register_embedding_profile(
        actor=actor,
        logical_id="default-embed",
        revision=1,
        provider="openai_compatible",
        scheme="https",
        host="embeddings.example.com",
        port=443,
        path="/v1/embeddings",
        model="text-embed-3",
        secret_ref="secret:embed-token",  # noqa: S106
        dimensions=1536,
        index_type="vector",
        normalize=True,
        distance_metric="cosine",
        timeout_seconds=30,
        max_response_bytes=5_000_000,
        max_batch_size=64,
    )


def test_registration_is_platform_admin_only_and_redacted() -> None:
    member = get_user_model().objects.create_user(username="member")
    with pytest.raises(EmbeddingProfileAuthorizationError, match="PLATFORM_ADMIN_REQUIRED"):
        _register(member)
    assert AuditEvent.objects.filter(action="embedding_profile.create", outcome="deny").exists()

    admin = get_user_model().objects.create_superuser(username="platform", password=None)
    profile = _register(admin)
    event = AuditEvent.objects.get(action="embedding_profile.create", outcome="success")
    assert event.resource_id == str(profile.public_id)
    raw = json.dumps(event.after)
    assert "embeddings.example.com" not in raw  # endpoint absent from audit
    assert "embed-token" not in raw  # secret ref absent from audit


def test_profile_is_immutable() -> None:
    admin = get_user_model().objects.create_superuser(username="platform", password=None)
    profile = _register(admin)
    profile.host = "other.example.com"
    with pytest.raises(ValueError, match="immutable"):
        profile.save()
    with pytest.raises(ValueError, match="cannot be deleted"):
        profile.delete()


def test_grant_is_platform_admin_only_and_idempotent() -> None:
    admin = get_user_model().objects.create_superuser(username="platform", password=None)
    profile = _register(admin)
    org = Organization.objects.create(slug="t", name="T")

    member = get_user_model().objects.create_user(username="member")
    with pytest.raises(EmbeddingProfileAuthorizationError):
        grant_embedding_profile(actor=member, organization=org, embedding_profile=profile)

    grant_embedding_profile(actor=admin, organization=org, embedding_profile=profile)
    grant_embedding_profile(actor=admin, organization=org, embedding_profile=profile)  # idempotent
    assert TenantEmbeddingProfileGrant.objects.filter(organization=org).count() == 1
    assert AuditEvent.objects.filter(action="embedding_profile.grant", outcome="success").exists()


def test_disable_is_platform_only_and_blocks_new_grants() -> None:
    admin = get_user_model().objects.create_superuser(username="platform", password=None)
    member = get_user_model().objects.create_user(username="member")
    profile = _register(admin)
    organization = Organization.objects.create(slug="disabled-grant", name="Disabled grant")

    with pytest.raises(EmbeddingProfileAuthorizationError, match="PLATFORM_ADMIN_REQUIRED"):
        disable_embedding_profile(actor=member, embedding_profile=profile)
    disable_embedding_profile(actor=admin, embedding_profile=profile)
    disable_embedding_profile(actor=admin, embedding_profile=profile)

    with pytest.raises(EmbeddingProfileAuthorizationError, match="EMBEDDING_PROFILE_DISABLED"):
        grant_embedding_profile(
            actor=admin,
            organization=organization,
            embedding_profile=profile,
        )
    assert not TenantEmbeddingProfileGrant.objects.filter(organization=organization).exists()
    assert (
        AuditEvent.objects.filter(action="embedding_profile.disable", outcome="success").count()
        == 1
    )
