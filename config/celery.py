"""Celery application.

One immutable image runs multiple roles by selecting a queue (see the v3 plan
§24.1): ``runtime`` (workflow/agent), ``ingestion`` (source ingestion/indexing),
and ``eval`` (release-gate evaluation), plus ``default`` for miscellaneous work.
"""

from __future__ import annotations

import os

from celery import Celery
from kombu import Queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("agenthub")

# All Celery config lives in Django settings under the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Dedicated queues keep long-running ingestion/eval/agent work off the request
# latency path and let each worker role scale independently.
app.conf.task_queues = (
    Queue("default"),
    Queue("runtime"),
    Queue("ingestion"),
    Queue("eval"),
)
app.conf.task_default_queue = "default"

app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - operational smoke task
    """Trivial task used to confirm broker/worker wiring in a new environment."""
    return f"request: {self.request!r}"
