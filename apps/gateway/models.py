"""Gateway persistence: idempotency records (v3 plan §9.1, §9.5).

An idempotency key is scoped per consumer. Replaying the same key with the same
request body returns the stored response; a differing body is a conflict (409).
"""

from __future__ import annotations

from django.db import models

from apps.identity.models import Consumer


class IdempotencyRecord(models.Model):
    consumer = models.ForeignKey(
        Consumer, on_delete=models.CASCADE, related_name="idempotency_records"
    )
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "key"], name="uniq_idempotency_consumer_key"
            )
        ]

    def __str__(self) -> str:
        return f"idem:{self.consumer_id}:{self.key}"
