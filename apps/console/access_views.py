"""Human-readable, preview-first scenario access management."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.catalog.models import AIProject, Scenario, ScenarioAccessMode
from apps.console.scoping import scoped_projects
from apps.identity.access_transition import (
    AccessGrant,
    apply_scenario_access,
    preview_scenario_access,
)
from apps.identity.assignment_services import AssignmentError
from apps.identity.authorization import (
    Capability,
    _active_assignments,
    authorize,
    authorized_scenarios,
)
from apps.identity.models import (
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.identity.project_access import apply_project_access, preview_project_access
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import OrganizationMembership

_ROLES = [
    ("", "Erişim verme"),
    (ScenarioResponsibility.VIEWER, "Görüntüleyen"),
    (ScenarioResponsibility.EDITOR, "Düzenleyen"),
    (ScenarioResponsibility.MANAGER, "Yönetici"),
]
_LABELS = {
    "project.view": "Projeyi görme",
    "project.manage": "Proje ayarlarını düzenleme",
    "project.access.manage": "Proje erişimini yönetme",
    "scenario.create": "Senaryo oluşturma",
    "scenario.view": "Senaryoyu görme",
    "scenario.edit": "Senaryoyu düzenleme",
    "scenario.test": "Senaryoyu test etme",
    "scenario.release": "Yayın yönetimi",
    "scenario.access.manage": "Senaryo erişimini yönetme",
    "runtime.view": "Çalışmaları izleme",
    "runtime.cancel": "Çalışmaları iptal etme",
    "runtime.pause": "Çalışmayı duraklatma",
    "runtime.resume": "Çalışmayı sürdürme",
    "scenario.approval.view": "Onayları görme",
    "scenario.approval.decide": "Araç işlemini onaylama",
}
_ERRORS = {
    "PROJECT_ACCESS_MANAGEMENT_REQUIRED": "Bu projenin erişimini yönetme yetkiniz yok.",
    "ACCESS_PREVIEW_STALE": "Erişim bilgileri değişti. Güncel durumla yeniden önizleyin.",
    "ACCESS_PREVIEW_INVALID_OR_EXPIRED": "Önizleme geçersiz veya süresi dolmuş. Yeniden önizleyin.",
    "LAST_SCENARIO_MANAGER": "Özel erişim için en az bir süresiz senaryo yöneticisi seçin.",
    "LAST_PROJECT_MANAGER": "Devralma için önce projeye süresiz bir proje yöneticisi atanmalı.",
    "ACCESS_PREVIEW_TOO_LARGE": "Bu ekranda en fazla 500 aktif üyenin erişimi yönetilebilir.",
    "SCENARIO_ACCESS_MANAGEMENT_REQUIRED": "Bu senaryonun erişimini yönetme yetkiniz yok.",
    "ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED": (
        "Seçilen üyelerden biri artık aktif değil. Yeniden önizleyin."
    ),
    "INVALID_ACCESS_EXPIRY": "Seçilen atamanın süresi dolmuş. Güncel durumla yeniden önizleyin.",
}

_PROJECT_ROLES = [
    ("", "Erişim verme"),
    (ProjectResponsibility.VIEWER, "Görüntüleyen"),
    (ProjectResponsibility.EDITOR, "Düzenleyen"),
    (ProjectResponsibility.MANAGER, "Yönetici"),
]


class ProjectAccessForm(forms.Form):
    def __init__(
        self,
        *args: Any,
        members: list[OrganizationMembership],
        assignments: dict[tuple[int, str], Any],
        **kwargs: Any,
    ):
        kwargs["initial"] = {
            f"member_{member.pk}": role
            for member in members
            for role, _ in _PROJECT_ROLES[1:]
            if (member.pk, role) in assignments
        }
        super().__init__(*args, **kwargs)
        self.members, self.assignments = members, assignments
        for member in members:
            self.fields[f"member_{member.pk}"] = forms.ChoiceField(
                label=member.user.get_username(), required=False, choices=_PROJECT_ROLES
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if set(self.data) - {*self.fields, "csrfmiddlewaretoken", "action"}:
            raise forms.ValidationError("Geçersiz üye veya alan gönderildi. Sayfayı yenileyin.")
        return cleaned

    def selected_grants(self) -> tuple[AccessGrant, ...]:
        result = []
        for member in self.members:
            role = self.cleaned_data.get(f"member_{member.pk}")
            if role:
                current = self.assignments.get((member.pk, role))
                result.append(AccessGrant(member.pk, role, current.expires_at if current else None))
        return tuple(result)


@login_required
@require_http_methods(["GET", "POST"])
def project_access(request: HttpRequest, public_id: object) -> HttpResponse:
    project: AIProject = get_object_or_404(scoped_projects(request.user), public_id=public_id)
    if not authorize(
        user=request.user, capability=Capability.PROJECT_ACCESS_MANAGE, project=project
    ).allowed:
        raise Http404
    set_tenant_context(project.organization_id)
    error = ""
    if request.method == "POST" and request.POST.get("action") == "apply":
        try:
            apply_project_access(
                project=project,
                actor=request.user,
                token=request.POST.get("preview_token", ""),
                request_id=str(getattr(request, "request_id", ""))[:64],
                trace_id=str(getattr(request, "trace_id", ""))[:64],
            )
            messages.success(request, "Proje erişimi güncellendi.")
            return redirect("console:project_detail_public", public_id=project.public_id)
        except AssignmentError as exc:
            error = _ERRORS.get(exc.code, "Erişim güncellenemedi. Yeniden önizleyin.")
    members = list(
        OrganizationMembership.objects.filter(
            organization_id=project.organization_id,
            status="active",
            user__is_active=True,
            user__is_superuser=False,
        )
        .select_related("user")
        .order_by("user__username", "pk")[:501]
    )
    if len(members) > 500:
        return render(
            request,
            "console/project_access.html",
            {"project": project, "error": _ERRORS["ACCESS_PREVIEW_TOO_LARGE"]},
            status=400,
        )
    assignments = {
        (row.membership_id, row.responsibility): row
        for row in _active_assignments(
            ProjectResponsibilityAssignment.objects.filter(project=project)
        )
    }
    preview_post = request.method == "POST" and request.POST.get("action") == "preview"
    form = ProjectAccessForm(
        request.POST if preview_post else None, members=members, assignments=assignments
    )
    preview, changes, grant_rows = None, [], []
    if preview_post and form.is_valid():
        try:
            preview = preview_project_access(
                project=project, actor=request.user, grants=form.selected_grants()
            )
            changes = [
                {
                    "username": row.username,
                    "scope": row.scope,
                    "gained": [_LABELS.get(cap, "Ek kapsam yetkisi") for cap in row.gained],
                    "lost": [_LABELS.get(cap, "Kapsam yetkisi") for cap in row.lost],
                }
                for row in preview.changes
            ]
            names = {member.pk: member.user.get_username() for member in members}
            grant_rows = [
                {
                    "username": names[row.membership_id],
                    "role": dict(_PROJECT_ROLES)[row.role],
                    "expires_at": row.expires_at,
                }
                for row in preview.grants
            ]
        except AssignmentError as exc:
            error = _ERRORS.get(exc.code, "Önizleme hazırlanamadı. Seçimleri kontrol edin.")
    return render(
        request,
        "console/project_access.html",
        {
            "project": project,
            "form": form,
            "preview": preview,
            "changes": changes,
            "grant_rows": grant_rows,
            "error": error,
        },
        status=400 if error or (preview_post and not form.is_valid()) else 200,
    )


class ScenarioAccessForm(forms.Form):
    mode = forms.ChoiceField(
        label="Erişim düzeni",
        choices=[
            ("", "Bir erişim düzeni seçin"),
            (ScenarioAccessMode.INHERIT, "Projeden devral"),
            (ScenarioAccessMode.PRIVATE, "Bu senaryoya özel erişim"),
        ],
    )

    def __init__(
        self,
        *args: Any,
        members: list[OrganizationMembership],
        scenario: Scenario,
        assignments: dict[tuple[int, str], Any],
        **kwargs: Any,
    ):
        initial = {"mode": scenario.access_mode if scenario.access_mode != "legacy" else ""}
        for member in members:
            for role, _ in _ROLES[1:]:
                if (
                    scenario.access_mode != ScenarioAccessMode.INHERIT
                    and (member.pk, role) in assignments
                ):
                    initial[f"member_{member.pk}"] = role
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.members = members
        self.assignments = assignments
        for member in members:
            self.fields[f"member_{member.pk}"] = forms.ChoiceField(
                label=member.user.get_username(),
                required=False,
                choices=_ROLES,
            )

    def selected_grants(self) -> tuple[AccessGrant, ...]:
        if self.cleaned_data["mode"] != "private":
            return ()
        grants = []
        for member in self.members:
            role = self.cleaned_data.get(f"member_{member.pk}")
            if role:
                current = self.assignments.get((member.pk, role))
                grants.append(AccessGrant(member.pk, role, current.expires_at if current else None))
        return tuple(grants)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if set(self.data) - {*self.fields, "csrfmiddlewaretoken", "action"}:
            raise forms.ValidationError("Geçersiz üye veya alan gönderildi. Sayfayı yenileyin.")
        return cleaned


@login_required
@require_http_methods(["GET", "POST"])
def scenario_access(request: HttpRequest, public_id: object) -> HttpResponse:
    scenario = get_object_or_404(
        authorized_scenarios(request.user, Capability.SCENARIO_ACCESS_MANAGE), public_id=public_id
    )
    set_tenant_context(scenario.organization_id)
    error = ""
    if request.method == "POST" and request.POST.get("action") == "apply":
        try:
            apply_scenario_access(
                scenario=scenario,
                actor=request.user,
                token=request.POST.get("preview_token", ""),
                request_id=str(getattr(request, "request_id", ""))[:64],
                trace_id=str(getattr(request, "trace_id", ""))[:64],
            )
            messages.success(request, "Senaryo erişimi güncellendi.")
            return redirect("console:scenario_access", public_id=scenario.public_id)
        except AssignmentError as exc:
            error = _ERRORS.get(
                exc.code, "Erişim güncellenemedi. Güncel durumla yeniden önizleyin."
            )
    members = list(
        OrganizationMembership.objects.filter(
            organization=scenario.organization,
            status="active",
            user__is_active=True,
            user__is_superuser=False,
        )
        .select_related("user")
        .order_by("user__username", "pk")[:501]
    )
    if len(members) > 500:
        return render(
            request,
            "console/scenario_access.html",
            {
                "scenario": scenario,
                "error": _ERRORS["ACCESS_PREVIEW_TOO_LARGE"],
            },
            status=400,
        )
    assignments = {
        (row.membership_id, row.responsibility): row
        for row in _active_assignments(
            ScenarioResponsibilityAssignment.objects.filter(scenario=scenario)
        )
    }
    preview_post = request.method == "POST" and request.POST.get("action") == "preview"
    form = ScenarioAccessForm(
        request.POST if preview_post else None,
        members=members,
        scenario=scenario,
        assignments=assignments,
    )
    preview = None
    changes = []
    grant_rows = []
    if preview_post and form.is_valid():
        try:
            preview = preview_scenario_access(
                scenario=scenario,
                actor=request.user,
                mode=form.cleaned_data["mode"],
                grants=form.selected_grants(),
            )
            names = {member.pk: member.user.get_username() for member in members}
            changes = [
                {
                    "username": delta.username,
                    "gained": [_LABELS.get(cap, "Ek kapsam yetkisi") for cap in delta.gained],
                    "lost": [_LABELS.get(cap, "Kapsam yetkisi") for cap in delta.lost],
                }
                for delta in preview.changes
            ]
            grant_rows = [
                {
                    "username": names[grant.membership_id],
                    "role": dict(_ROLES)[grant.role],
                    "expires_at": grant.expires_at,
                }
                for grant in preview.grants
            ]
        except AssignmentError as exc:
            error = _ERRORS.get(exc.code, "Önizleme hazırlanamadı. Seçimleri kontrol edin.")
    return render(
        request,
        "console/scenario_access.html",
        {
            "scenario": scenario,
            "form": form,
            "member_fields": list(form)[1:],
            "preview": preview,
            "changes": changes,
            "grant_rows": grant_rows,
            "error": error,
            "target_mode": dict(ScenarioAccessMode.choices).get(preview.target_mode)
            if preview
            else "",
            "can_view_scenario": authorized_scenarios(request.user, Capability.SCENARIO_VIEW)
            .filter(pk=scenario.pk)
            .exists(),
        },
        status=400 if error or (preview_post and not form.is_valid()) else 200,
    )
