"""AgentHub Django project configuration package.

Importing the Celery app here ensures it is loaded when Django starts, so that
shared_task-decorated tasks register against the correct broker/backend.
"""

from config.celery import app as celery_app

__all__ = ["celery_app"]
