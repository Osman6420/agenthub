"""Usage/metering events (v3 plan §9.4, §21).

One row per gateway request: cost/performance signal with stable references and no
PII. Token counts are populated once the runtime generates output (Sprint 4+).
"""

from __future__ import annotations

from django.db import models


class UsageEvent(models.Model):
    request_id = models.CharField(max_length=64, db_index=True)
    organization_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    scenario_id = models.BigIntegerField(null=True, blank=True)
    release_id = models.BigIntegerField(null=True, blank=True)
    consumer_id = models.BigIntegerField(null=True, blank=True)
    operation = models.CharField(max_length=32)
    status = models.CharField(max_length=32)
    error_code = models.CharField(max_length=64, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"usage:{self.operation}:{self.status}:{self.request_id}"
