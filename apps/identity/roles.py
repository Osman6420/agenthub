"""Operator roles (v3 plan §6.1).

Roles are organization-scoped except ``platform_admin``, which in Sprint 1 is
represented by Django ``is_superuser`` (see ADR-0001 open question). In production
these map from LDAP/AD directory groups.
"""

from __future__ import annotations

from django.db import models


class Role(models.TextChoices):
    PLATFORM_ADMIN = "platform_admin", "Platform admin"
    ORGANIZATION_ADMIN = "organization_admin", "Organization admin"
    DOCUMENT_MANAGER = "document_manager", "Document manager"
    PROJECT_OWNER = "project_owner", "Project owner"
    SCENARIO_EDITOR = "scenario_editor", "Scenario editor"
    RELEASE_MANAGER = "release_manager", "Release manager"
    APPROVER = "approver", "Approver"
    AUDITOR = "auditor", "Auditor"
