"""Preview and atomically replace explicit basic project roles, preserving legacy roles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.services import record_event
from apps.catalog.models import AIProject, ScenarioAccessMode
from apps.identity.access_transition import (
    AccessDelta,
    AccessGrant,
    _capabilities,
    _scope_snapshot,
    _serialize_grants,
)
from apps.identity.assignment_services import AssignmentError
from apps.identity.authorization import Capability, authorize
from apps.identity.models import ProjectResponsibility, ProjectResponsibilityAssignment
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization

_SALT = "agenthub.project-access.v1"
BASIC_PROJECT_ROLES = frozenset(
    {ProjectResponsibility.VIEWER, ProjectResponsibility.EDITOR, ProjectResponsibility.MANAGER}
)
_PROJECT_CAPS = frozenset(
    {
        Capability.PROJECT_VIEW,
        Capability.PROJECT_MANAGE,
        Capability.PROJECT_ACCESS_MANAGE,
        Capability.SCENARIO_CREATE,
    }
)
_SCENARIO_CAPS = frozenset(
    cap
    for cap in Capability
    if (cap.value.startswith("scenario.") and cap != Capability.SCENARIO_CREATE)
    or cap.value.startswith("runtime.")
)


@dataclass(frozen=True)
class ProjectAccessDelta(AccessDelta):
    scope: str


@dataclass(frozen=True)
class ProjectAccessPreview:
    token: str
    changes: tuple[ProjectAccessDelta, ...]
    grants: tuple[AccessGrant, ...]


def _require_manager(actor: Any, project: AIProject) -> None:
    if (
        project.organization.status != "active"
        or not authorize(
            user=actor, capability=Capability.PROJECT_ACCESS_MANAGE, project=project
        ).allowed
    ):
        raise AssignmentError("PROJECT_ACCESS_MANAGEMENT_REQUIRED")


def _validate(members: list[Any], grants: list[dict[str, Any]]) -> None:
    ids = {member.pk for member in members}
    if any(row["membership_id"] not in ids for row in grants):
        raise AssignmentError("ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED")
    if not any(
        row["role"] == ProjectResponsibility.MANAGER and row["expires_at"] is None for row in grants
    ):
        raise AssignmentError("LAST_PROJECT_MANAGER")


@transaction.atomic
def preview_project_access(
    *, project: AIProject, actor: Any, grants: tuple[AccessGrant, ...]
) -> ProjectAccessPreview:
    set_tenant_context(project.organization_id)
    current = AIProject.objects.select_related("organization").get(
        pk=project.pk, organization_id=project.organization_id
    )
    _require_manager(actor, current)
    requested = _serialize_grants(grants, BASIC_PROJECT_ROLES)
    members, state, baseline = _scope_snapshot(current)
    _validate(members, requested)
    after = {
        **state,
        "project": [
            row for row in state["project"] if row["responsibility"] not in BASIC_PROJECT_ROLES
        ]
        + [
            {"membership_id": row["membership_id"], "responsibility": row["role"]}
            for row in requested
        ],
    }
    scopes = [(current.name, "legacy", None, _PROJECT_CAPS)] + [
        (row["name"], row["access_mode"], row["pk"], _SCENARIO_CAPS) for row in state["scenarios"]
    ]
    changes = []
    for member in members:
        # Restrict in-memory role rows once per member; avoid scanning every
        # organization assignment for every member/scenario pair.
        own = {
            **state,
            **{
                key: [row for row in state[key] if row["membership_id"] == member.pk]
                for key in ("organization", "project", "scenario")
            },
        }
        next_project = [row for row in after["project"] if row["membership_id"] == member.pk]
        comparisons = []
        for name, mode, scenario_id, caps in scopes:
            if mode not in ScenarioAccessMode.values:
                raise AssignmentError("INVALID_ACCESS_MODE")
            scoped = {
                **own,
                "scenario": [row for row in own["scenario"] if row["scenario_id"] == scenario_id],
            }
            next_scope = {**scoped, "project": next_project}
            before_caps = _capabilities(member, scoped, mode, None) & caps
            after_caps = _capabilities(member, next_scope, mode, None) & caps
            comparisons.append((name, before_caps, after_caps))
        if any(Capability.SCENARIO_VIEW in before for _, before, _ in comparisons[1:]):
            comparisons[0][1].add(Capability.PROJECT_VIEW)
        if any(Capability.SCENARIO_VIEW in after_caps for _, _, after_caps in comparisons[1:]):
            comparisons[0][2].add(Capability.PROJECT_VIEW)
        for name, before_caps, after_caps in comparisons:
            if before_caps != after_caps:
                changes.append(
                    ProjectAccessDelta(
                        member.pk,
                        member.user.get_username(),
                        tuple(sorted(after_caps - before_caps)),
                        tuple(sorted(before_caps - after_caps)),
                        name,
                    )
                )
                if len(changes) > 5000:
                    raise AssignmentError("ACCESS_PREVIEW_TOO_LARGE")
    return ProjectAccessPreview(
        signing.dumps(
            {
                "actor": actor.pk,
                "project": current.pk,
                "organization": current.organization_id,
                "baseline": baseline,
                "grants": requested,
            },
            salt=_SALT,
        ),
        tuple(changes),
        grants,
    )


def _audit(
    project: AIProject,
    actor: Any,
    outcome: str,
    reason: str,
    request_id: str,
    trace_id: str,
    **fields: Any,
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor.get_username(),
        organization_id=project.organization_id,
        action="responsibility.project.access_changed",
        outcome=outcome,
        resource_type="project",
        resource_id=str(project.public_id),
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
        **fields,
    )


def apply_project_access(
    *, project: AIProject, actor: Any, token: str, request_id: str = "", trace_id: str = ""
) -> AIProject:
    try:
        if not isinstance(token, str) or len(token) > 150_000:
            raise signing.BadSignature()
        payload = signing.loads(token, salt=_SALT, max_age=600)
        if (
            payload["actor"] != actor.pk
            or payload["project"] != project.pk
            or payload["organization"] != project.organization_id
        ):
            raise signing.BadSignature()
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        _audit(project, actor, "deny", "ACCESS_PREVIEW_INVALID_OR_EXPIRED", request_id, trace_id)
        raise AssignmentError("ACCESS_PREVIEW_INVALID_OR_EXPIRED") from exc
    try:
        with transaction.atomic():
            set_tenant_context(project.organization_id)
            Organization.objects.select_for_update().get(pk=project.organization_id)
            current = (
                AIProject.objects.select_for_update()
                .select_related("organization")
                .get(pk=project.pk, organization_id=project.organization_id)
            )
            _require_manager(actor, current)
            change_id = hashlib.sha256(token.encode()).hexdigest()
            if current.access_change_id == change_id:
                return current
            members, state, baseline = _scope_snapshot(current)
            if baseline != payload["baseline"]:
                raise AssignmentError("ACCESS_PREVIEW_STALE")
            grants = tuple(
                AccessGrant(
                    row["membership_id"],
                    row["role"],
                    parse_datetime(row["expires_at"]) if row["expires_at"] else None,
                )
                for row in payload["grants"]
            )
            requested = _serialize_grants(grants, BASIC_PROJECT_ROLES)
            _validate(members, requested)
            chosen = {(grant.membership_id, grant.role): grant for grant in grants}
            for assignment in ProjectResponsibilityAssignment.objects.select_for_update().filter(
                project=current,
                organization_id=current.organization_id,
                responsibility__in=BASIC_PROJECT_ROLES,
            ):
                grant = chosen.pop((assignment.membership_id, assignment.responsibility), None)
                if grant is not None:
                    assignment.status = "active"
                    assignment.assigned_by = actor
                    assignment.expires_at = grant.expires_at
                    assignment.revoked_at = assignment.revoked_by = None
                    assignment.save()
                elif assignment.status == "active":
                    ProjectResponsibilityAssignment.objects.filter(pk=assignment.pk).update(
                        status="revoked",
                        revoked_by=actor,
                        revoked_at=timezone.now(),
                        updated_at=timezone.now(),
                    )
            for grant in chosen.values():
                ProjectResponsibilityAssignment.objects.create(
                    project=current,
                    organization_id=current.organization_id,
                    membership_id=grant.membership_id,
                    responsibility=grant.role,
                    expires_at=grant.expires_at,
                    assigned_by=actor,
                )
            current.access_revision += 1
            current.access_change_id = change_id
            current.save(update_fields=["access_revision", "access_change_id", "updated_at"])
            _audit(
                current,
                actor,
                "success",
                "ACCESS_PREVIEW_APPLIED",
                request_id,
                trace_id,
                before={"revision": current.access_revision - 1},
                after={
                    "revision": current.access_revision,
                    "change_id": change_id,
                    "grants": requested,
                },
            )
            return current
    except AssignmentError as exc:
        _audit(project, actor, "deny", exc.code, request_id, trace_id)
        raise
