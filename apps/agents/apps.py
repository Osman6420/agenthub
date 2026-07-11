from __future__ import annotations

from django.apps import AppConfig


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.agents"
    verbose_name = "Agents"

    def ready(self) -> None:
        from apps.agents import signals  # noqa: F401  (connect signal receivers)
