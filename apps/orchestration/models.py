from __future__ import annotations

import uuid
from typing import Any

from django.db import models


class ModelProfileStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class ModelProfile(models.Model):
    """Platform-managed immutable model-egress configuration (ADR-0002)."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    logical_id = models.CharField(max_length=128)
    revision = models.PositiveIntegerField()
    provider = models.CharField(max_length=64, default="openai_compatible")
    scheme = models.CharField(max_length=8, default="https")
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    path = models.CharField(max_length=512, default="/v1/chat/completions")
    model = models.CharField(max_length=200)
    secret_ref = models.CharField(max_length=160)
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_response_bytes = models.PositiveIntegerField(default=1_000_000)
    max_output_tokens = models.PositiveIntegerField(default=2048)
    status = models.CharField(
        max_length=16, choices=ModelProfileStatus.choices, default=ModelProfileStatus.ACTIVE
    )
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["logical_id", "revision"], name="uniq_model_profile_logical_revision"
            )
        ]

    def __str__(self) -> str:
        return f"model-profile:{self.logical_id}:r{self.revision}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= {"status"}:
                raise ValueError("ModelProfile is immutable; only status may change")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("ModelProfile is immutable and cannot be deleted")
