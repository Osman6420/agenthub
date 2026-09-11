"""Presentation-only navigation; destinations never confer authorization."""

from __future__ import annotations

from django.http import HttpRequest
from django.urls import reverse

SECTIONS = {
    "dashboard": ("Ana Sayfa", "dashboard"),
    "projects": ("Projeler", "projects"),
    "scenarios": ("Senaryolar", "scenarios"),
    "documents": ("Dokümanlar", "documents"),
    "questions": ("Testler", "question_sets"),
    "consumers": ("İstemciler", "consumers"),
    "runs": ("Çalıştırmalar", "runs"),
    "approvals": ("Onaylar", "tool_approvals"),
    "members": ("Kullanıcılar ve yetkiler", "organization_members"),
    "platform": ("Platform kurulumu", "platform_setup"),
}


def navigation_context(request: HttpRequest) -> dict[str, object]:
    match = request.resolver_match
    name = match.url_name if match else ""
    name = name or ""
    section = "dashboard"
    if name.startswith(("scenario", "project_scenario", "release", "artifact", "builder")):
        section = "scenarios"
    elif name.startswith("project"):
        section = "projects"
    elif name.startswith(
        (
            "document",
            "advanced_document",
            "connector",
            "confluence",
            "rest_",
            "mcp_source",
            "mcp_schedule",
        )
    ):
        section = "documents"
    elif name.startswith("question"):
        section = "questions"
    elif name.startswith(("consumer", "binding")):
        section = "consumers"
    elif name.startswith("tool_"):
        section = "approvals"
    elif name.startswith(("run", "workflow")):
        section = "runs"
    elif name.startswith(("organization_member", "delegated_assignment")):
        section = "members"
    elif name.startswith(("platform", "retention")):
        section = "platform"
    elif name == "health_issues" and match:
        section = (
            "documents"
            if match.kwargs.get("category") in {"promotable-index", "failed-index-build"}
            else "scenarios"
        )
    label, root = SECTIONS[section]
    return {
        "navigation_section": section,
        "navigation_label": label,
        "navigation_url": reverse(f"console:{root}"),
        "navigation_is_child": name != root,
    }
