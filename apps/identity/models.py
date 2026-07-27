"""Machine identity: consumers and their scenario bindings.

A ``Consumer`` is a backend/app/MCP client/agent that may call the gateway. A
``ConsumerBinding`` grants a consumer access to one scenario with a set of
capabilities. A binding may only reference a scenario in the consumer's own
organization, and only a known capability allowlist (v3 plan §9, §10.2).
"""

from __future__ import annotations

import uuid
from typing import cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.identity.capabilities import validate_capabilities
from apps.tenancy.models import (
    Organization,
    OrganizationMembership,
    TimeStampedModel,
    ensure_immutable_public_id,
)


class GlobalAdministrator(TimeStampedModel):
    """The single daily application administrator identity.

    This is deliberately separate from Django's exceptional ``is_superuser``
    recovery identity. Assignment is performed through an audited service in a
    later Part 2.1 delivery slice; ordinary organization membership forms must
    never expose this model.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="global_administrator",
    )
    scope = models.CharField(max_length=16, default="global", unique=True, editable=False)

    class Meta:
        verbose_name = "global administrator"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scope="global"),
                name="global_administrator_single_scope",
            )
        ]

    def clean(self) -> None:
        if self.scope != "global":
            raise ValidationError({"scope": "global administrator scope must be global"})
        if self.user_id and self.user.is_superuser:
            raise ValidationError(
                {"user": "global administrator must be separate from the recovery superadmin"}
            )
        if self.user_id and not self.user.is_active:
            raise ValidationError({"user": "global administrator must be active"})

    def __str__(self) -> str:
        return f"global-administrator:{self.user_id}"


class DelegatedAssignmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


def _revocation_constraint(name: str) -> models.CheckConstraint:
    """A revoked assignment must record who withdrew it and when; an active one must not."""
    return models.CheckConstraint(
        condition=(
            models.Q(
                status=DelegatedAssignmentStatus.ACTIVE,
                revoked_at__isnull=True,
                revoked_by__isnull=True,
            )
            | models.Q(
                status=DelegatedAssignmentStatus.REVOKED,
                revoked_at__isnull=False,
                revoked_by__isnull=False,
            )
        ),
        name=name,
    )


class ProjectAdministratorAssignment(TimeStampedModel):
    """Delegates administration of one project to one organization member."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="project_administrator_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_administrator_assignments",
    )
    project = models.ForeignKey(
        "catalog.AIProject",
        on_delete=models.CASCADE,
        related_name="administrator_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_project_administrator_assignments",
    )
    status = models.CharField(
        max_length=16,
        choices=DelegatedAssignmentStatus.choices,
        default=DelegatedAssignmentStatus.ACTIVE,
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_project_administrator_assignments",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "user"],
                name="uniq_project_administrator_assignment",
            ),
            _revocation_constraint("project_administrator_assignment_revocation_complete"),
        ]
        ordering = ["organization_id", "project_id", "user_id"]

    def clean(self) -> None:
        _validate_delegated_assignment(
            organization_id=self.organization_id,
            target_organization_id=self.project.organization_id if self.project_id else None,
            user=self.user if self.user_id else None,
        )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class ScenarioEditorAssignment(TimeStampedModel):
    """Delegates edit and test authority over one scenario."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="scenario_editor_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scenario_editor_assignments",
    )
    scenario = models.ForeignKey(
        "catalog.Scenario",
        on_delete=models.CASCADE,
        related_name="editor_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_scenario_editor_assignments",
    )
    status = models.CharField(
        max_length=16,
        choices=DelegatedAssignmentStatus.choices,
        default=DelegatedAssignmentStatus.ACTIVE,
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_scenario_editor_assignments",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "user"],
                name="uniq_scenario_editor_assignment",
            ),
            _revocation_constraint("scenario_editor_assignment_revocation_complete"),
        ]
        ordering = ["organization_id", "scenario_id", "user_id"]

    def clean(self) -> None:
        _validate_delegated_assignment(
            organization_id=self.organization_id,
            target_organization_id=self.scenario.organization_id if self.scenario_id else None,
            user=self.user if self.user_id else None,
        )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class DocumentSetManagerAssignment(TimeStampedModel):
    """Delegates content and operational responsibility for one document set."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="document_set_manager_assignments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_set_manager_assignments",
    )
    document_set = models.ForeignKey(
        "documents.DocumentSet",
        on_delete=models.CASCADE,
        related_name="manager_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_document_set_manager_assignments",
    )
    status = models.CharField(
        max_length=16,
        choices=DelegatedAssignmentStatus.choices,
        default=DelegatedAssignmentStatus.ACTIVE,
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_document_set_manager_assignments",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_set", "user"],
                name="uniq_document_set_manager_assignment",
            ),
            _revocation_constraint("document_set_manager_assignment_revocation_complete"),
        ]
        ordering = ["organization_id", "document_set_id", "user_id"]

    def clean(self) -> None:
        _validate_delegated_assignment(
            organization_id=self.organization_id,
            target_organization_id=(
                self.document_set.organization_id if self.document_set_id else None
            ),
            user=self.user if self.user_id else None,
        )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]


def _validate_delegated_assignment(
    *,
    organization_id: int | None,
    target_organization_id: int | None,
    user: object | None,
) -> None:
    if organization_id and target_organization_id != organization_id:
        raise ValidationError("assignment target must belong to the same organization")
    if user is not None:
        if not getattr(user, "is_active", False):
            raise ValidationError("assignment user must be active")
        if getattr(user, "is_superuser", False):
            raise ValidationError("recovery superadmin cannot receive delegated assignments")
        user_id = cast(int | str | None, getattr(user, "pk", None))
        if user_id is None or (
            organization_id
            and not OrganizationMembership.objects.filter(
                organization_id=organization_id,
                user_id=user_id,
            ).exists()
        ):
            raise ValidationError("assignment user must be an organization member")


class ConsumerProtocol(models.TextChoices):
    REST = "rest", "REST"
    MCP = "mcp", "MCP"


class ConsumerStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class Consumer(TimeStampedModel):
    """A system that can call the gateway on behalf of an organization."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="consumers"
    )
    subject = models.CharField(
        max_length=255,
        help_text="Stable authenticated subject (OIDC sub, service account, mTLS CN).",
    )
    name = models.CharField(max_length=200)
    protocol = models.CharField(max_length=8, choices=ConsumerProtocol.choices)
    status = models.CharField(
        max_length=16, choices=ConsumerStatus.choices, default=ConsumerStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "subject"],
                name="uniq_consumer_org_subject",
            )
        ]
        ordering = ["organization_id", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.subject})"

    def save(self, *args: object, **kwargs: object) -> None:
        ensure_immutable_public_id(self)
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    @property
    def is_active(self) -> bool:
        return self.status == ConsumerStatus.ACTIVE


class TokenStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class ConsumerToken(TimeStampedModel):
    """A bearer credential for a consumer. Only the SHA-256 hash is stored.

    The plaintext token is shown once at creation and never persisted. This is the
    default credential seam; OIDC/JWT/mTLS are added later without changing callers.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="consumer_tokens"
    )
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name="tokens")
    name = models.CharField(max_length=200)
    prefix = models.CharField(max_length=12, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=16, choices=TokenStatus.choices, default=TokenStatus.ACTIVE
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"token:{self.prefix}… ({self.consumer_id})"

    @property
    def is_active(self) -> bool:
        return self.status == TokenStatus.ACTIVE

    def save(self, *args: object, **kwargs: object) -> None:
        if self.consumer_id:
            consumer_org_id = self.consumer.organization_id
            if self.organization_id and self.organization_id != consumer_org_id:
                raise ValueError("token organization must match consumer organization")
            self.organization_id = consumer_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class BindingStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class ConsumerBinding(TimeStampedModel):
    """Grants a consumer access to a scenario with a capability set."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="consumer_bindings"
    )
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name="bindings")
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="consumer_bindings"
    )
    capabilities = models.JSONField(default=list)
    status = models.CharField(
        max_length=16, choices=BindingStatus.choices, default=BindingStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "scenario"],
                name="uniq_binding_consumer_scenario",
            )
        ]

    def __str__(self) -> str:
        return f"binding:{self.consumer_id}->{self.scenario_id}"

    def clean(self) -> None:
        # Capabilities must be a known allowlist.
        validate_capabilities(self.capabilities)
        # A binding may only cross into a scenario in the consumer's organization.
        if self.consumer_id and self.scenario_id:
            scenario_org_id = self.scenario.project.organization_id
            if scenario_org_id != self.consumer.organization_id:
                raise ValidationError("consumer and scenario must belong to the same organization")

    def save(self, *args: object, **kwargs: object) -> None:
        if self.consumer_id:
            consumer_org_id = self.consumer.organization_id
            if self.organization_id and self.organization_id != consumer_org_id:
                raise ValidationError("binding organization must match consumer organization")
            self.organization_id = consumer_org_id
        # Enforce invariants on every write (full_clean is not called automatically).
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    @property
    def is_active(self) -> bool:
        return self.status == BindingStatus.ACTIVE
