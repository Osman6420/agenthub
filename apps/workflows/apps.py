from __future__ import annotations

from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workflows"
    verbose_name = "Workflows"

    def ready(self) -> None:
        from apps.workflows import signals  # noqa: F401  (connect signal receivers)
