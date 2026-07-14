"""Machine identity: consumers and their scenario bindings.

A ``Consumer`` is a backend/app/MCP client/agent that may call the gateway. A
``ConsumerBinding`` grants a consumer access to one scenario with a set of
capabilities. A binding may only reference a scenario in the consumer's own
organization, and only a known capability allowlist (v3 plan §9, §10.2).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.identity.capabilities import validate_capabilities
from apps.tenancy.models import Organization, TimeStampedModel


class ConsumerProtocol(models.TextChoices):
    REST = "rest", "REST"
    MCP = "mcp", "MCP"


class ConsumerStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class Consumer(TimeStampedModel):
    """A system that can call the gateway on behalf of an organization."""

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
