"""Append-only audit trail (v3 plan §9.4, observability rules).

An ``AuditEvent`` records a state change or security-sensitive action with the
actor, action, target, authorization outcome, reason, and trace references. It must
never contain secrets or raw PII. Records are immutable: updates and deletes are
rejected at the model level; writes go through :mod:`apps.audit.services`.
"""

from __future__ import annotations

from django.db import models


class ActorType(models.TextChoices):
    USER = "user", "User"
    CONSUMER = "consumer", "Consumer"
    SYSTEM = "system", "System"


class Outcome(models.TextChoices):
    ALLOW = "allow", "Allow"
    DENY = "deny", "Deny"
    SUCCESS = "success", "Success"
    FAILURE = "failure", "Failure"


class AuditEvent(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    actor_id = models.CharField(max_length=255)
    organization_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100, blank=True)
    resource_id = models.CharField(max_length=255, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    reason = models.CharField(max_length=500, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    trace_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.action}:{self.outcome} by {self.actor_type}:{self.actor_id}"

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise ValueError("AuditEvent is append-only and cannot be modified")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValueError("AuditEvent is append-only and cannot be deleted")
