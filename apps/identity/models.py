"""Machine identity: consumers and their scenario bindings.

A ``Consumer`` is a backend/app/MCP client/agent that may call the gateway. A
``ConsumerBinding`` grants a consumer access to one scenario with a set of
capabilities. A binding may only reference a scenario in the consumer's own
organization, and only a known capability allowlist (v3 plan §9, §10.2).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.identity.capabilities import validate_capabilities
from apps.tenancy.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    TimeStampedModel,
    ensure_immutable_public_id,
)


class ResponsibilityStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class PlatformResponsibility(models.TextChoices):
    GLOBAL_ADMINISTRATOR = "global_administrator", "Global administrator"


class OrganizationResponsibility(models.TextChoices):
    ADMINISTRATOR = "organization_administrator", "Organization administrator"
    AUDITOR = "organization_auditor", "Organization auditor"


class ProjectResponsibility(models.TextChoices):
    VIEWER = "project_viewer", "Project viewer"
    EDITOR = "project_editor", "Proje düzenleyeni"
    MANAGER = "project_manager", "Proje yöneticisi"
    ADMINISTRATOR = "project_administrator", "Project administrator"


class ScenarioResponsibility(models.TextChoices):
    VIEWER = "scenario_viewer", "Scenario viewer"
    EDITOR = "scenario_editor", "Scenario editor"
    MANAGER = "scenario_manager", "Senaryo yöneticisi"
    RELEASE_MANAGER = "scenario_release_manager", "Scenario release manager"
    RUNTIME_OPERATOR = "scenario_runtime_operator", "Scenario runtime operator"
    APPROVER = "scenario_approver", "Scenario approver"


class DocumentSetResponsibility(models.TextChoices):
    METADATA_VIEWER = "document_set_metadata_viewer", "Document-set metadata viewer"
    CONTENT_READER = "document_set_content_reader", "Document-set content reader"
    MANAGER = "document_set_manager", "Document-set manager"


def _responsibility_revocation_constraint(name: str) -> models.CheckConstraint:
    return models.CheckConstraint(
        condition=(
            models.Q(
                status=ResponsibilityStatus.ACTIVE,
                revoked_at__isnull=True,
                revoked_by__isnull=True,
            )
            | models.Q(
                status=ResponsibilityStatus.REVOKED,
                revoked_at__isnull=False,
                revoked_by__isnull=False,
            )
        ),
        name=name,
    )


class PlatformResponsibilityAssignment(TimeStampedModel):
    """Daily platform authority, separate from exceptional Django superuser recovery."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="platform_responsibility_assignments",
    )
    responsibility = models.CharField(
        max_length=48,
        choices=PlatformResponsibility.choices,
        default=PlatformResponsibility.GLOBAL_ADMINISTRATOR,
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_platform_responsibility_assignments",
    )
    status = models.CharField(
        max_length=16,
        choices=ResponsibilityStatus.choices,
        default=ResponsibilityStatus.ACTIVE,
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_platform_responsibility_assignments",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["responsibility"],
                condition=models.Q(status=ResponsibilityStatus.ACTIVE),
                name="uniq_active_platform_responsibility",
            ),
            _responsibility_revocation_constraint(
                "platform_responsibility_assignment_revocation_complete"
            ),
        ]

    def clean(self) -> None:
        if self.user_id and (self.user.is_superuser or not self.user.is_active):
            raise ValidationError(
                {"user": "platform responsibility requires an active non-superuser"}
            )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class TenantResponsibilityAssignment(TimeStampedModel):
    """Shared lifecycle/provenance contract for exact tenant responsibility rows."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="+",
    )
    membership = models.ForeignKey(
        OrganizationMembership,
        on_delete=models.PROTECT,
        related_name="+",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=ResponsibilityStatus.choices,
        default=ResponsibilityStatus.ACTIVE,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def _validate_membership(self, target_organization_id: int | None) -> None:
        if not self.membership_id:
            return
        membership = self.membership
        if (
            membership.organization_id != self.organization_id
            or target_organization_id != self.organization_id
        ):
            raise ValidationError("responsibility scope must stay inside membership organization")
        if membership.status != MembershipStatus.ACTIVE:
            raise ValidationError("responsibility requires an active organization membership")
        if not membership.user.is_active or membership.user.is_superuser:
            raise ValidationError("responsibility requires an active non-superuser member")

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class OrganizationResponsibilityAssignment(TenantResponsibilityAssignment):
    responsibility = models.CharField(max_length=48, choices=OrganizationResponsibility.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "membership", "responsibility"],
                name="uniq_organization_responsibility_assignment",
            ),
            _responsibility_revocation_constraint(
                "organization_responsibility_assignment_revocation_complete"
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    responsibility=OrganizationResponsibility.ADMINISTRATOR,
                    expires_at__isnull=False,
                ),
                name="organization_administrator_non_expiring",
            ),
        ]
        ordering = ["organization_id", "membership_id", "responsibility"]

    def clean(self) -> None:
        self._validate_membership(self.organization_id)
        if (
            self.responsibility == OrganizationResponsibility.ADMINISTRATOR
            and self.expires_at is not None
        ):
            raise ValidationError({"expires_at": "organization administrator cannot expire"})


class ProjectResponsibilityAssignment(TenantResponsibilityAssignment):
    project = models.ForeignKey(
        "catalog.AIProject",
        on_delete=models.CASCADE,
        related_name="responsibility_assignments",
    )
    responsibility = models.CharField(max_length=48, choices=ProjectResponsibility.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "membership", "responsibility"],
                name="uniq_project_responsibility_assignment",
            ),
            _responsibility_revocation_constraint(
                "project_responsibility_assignment_revocation_complete"
            ),
        ]
        ordering = ["organization_id", "project_id", "membership_id", "responsibility"]

    def clean(self) -> None:
        self._validate_membership(self.project.organization_id if self.project_id else None)


class ScenarioResponsibilityAssignment(TenantResponsibilityAssignment):
    scenario = models.ForeignKey(
        "catalog.Scenario",
        on_delete=models.CASCADE,
        related_name="responsibility_assignments",
    )
    responsibility = models.CharField(max_length=48, choices=ScenarioResponsibility.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "membership", "responsibility"],
                name="uniq_scenario_responsibility_assignment",
            ),
            _responsibility_revocation_constraint(
                "scenario_responsibility_assignment_revocation_complete"
            ),
        ]
        ordering = ["organization_id", "scenario_id", "membership_id", "responsibility"]

    def clean(self) -> None:
        self._validate_membership(self.scenario.organization_id if self.scenario_id else None)


class DocumentSetResponsibilityAssignment(TenantResponsibilityAssignment):
    document_set = models.ForeignKey(
        "documents.DocumentSet",
        on_delete=models.CASCADE,
        related_name="responsibility_assignments",
    )
    responsibility = models.CharField(max_length=48, choices=DocumentSetResponsibility.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_set", "membership", "responsibility"],
                name="uniq_document_set_responsibility_assignment",
            ),
            _responsibility_revocation_constraint(
                "document_set_responsibility_assignment_revocation_complete"
            ),
        ]
        ordering = ["organization_id", "document_set_id", "membership_id", "responsibility"]

    def clean(self) -> None:
        self._validate_membership(
            self.document_set.organization_id if self.document_set_id else None
        )


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
