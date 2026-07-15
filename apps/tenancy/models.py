"""Tenancy: the organization boundary and membership.

Every tenant-owned record ultimately belongs to an :class:`Organization`. Isolation
is enforced in querysets/services (see :mod:`apps.tenancy.services`), not only in
the UI. A platform operator (Django ``is_superuser``) can cross organizations; all
other access is scoped to the user's memberships.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models

from apps.identity.roles import Role


class TimeStampedModel(models.Model):
    """Abstract base adding created/updated timestamps to domain records."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def ensure_immutable_public_id(instance: Any) -> None:
    """Reject mutation of a persisted public locator for Part 2 models."""
    if instance.pk is None:
        return
    persisted = (
        type(instance).objects.filter(pk=instance.pk).values_list("public_id", flat=True).first()
    )
    if persisted is not None and persisted != instance.public_id:
        raise ValueError("public_id is immutable")


class OrganizationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class Organization(TimeStampedModel):
    """A tenant boundary, ownership and membership unit."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.ACTIVE,
    )

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug

    @property
    def is_active(self) -> bool:
        return self.status == OrganizationStatus.ACTIVE


class OrganizationMembership(TimeStampedModel):
    """Maps a user to an organization with a role."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships"
    )
    role = models.CharField(max_length=32, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="uniq_membership_org_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.organization_id}:{self.role}"
