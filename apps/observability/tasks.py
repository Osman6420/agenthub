"""Scheduled observability tasks (P2.6.11).

The retention beat task runs in **report mode only** — it counts bulky-state rows past the
90-day window and never deletes. Deletion stays a deliberate, owner-approved operator action
via the ``purge_retention --commit`` command or the platform-admin console surface, so a
scheduler can never silently destroy state.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from apps.observability.retention import run_retention

logger = logging.getLogger("agenthub.observability.retention")


@shared_task(queue="runtime")
def report_retention_backlog() -> dict[str, Any]:
    """Report (never purge) eligible bulky-state counts for retention monitoring."""
    reports = run_retention(commit=False)
    summary = {r.retention_class: r.eligible for r in reports}
    logger.info("retention_report", extra={"retention_backlog": summary})
    return summary
