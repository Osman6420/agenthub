"""Console authoring forms.

Each form scopes its foreign-key choices to what the operator may administer/author,
so the UI cannot offer a parent org/project outside the user's scope. Views re-check
authorization server-side before saving (defense in depth).
"""

from __future__ import annotations

from typing import Any, cast

from django import forms
from django.db.models import QuerySet

from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.services import admin_organization_ids, author_organization_ids


def _scope(qs: QuerySet, ids: set[int] | None, field: str = "id") -> QuerySet:
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["slug", "name", "status"]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)


class ProjectForm(forms.ModelForm):
    owner = forms.ChoiceField(required=False, choices=())

    class Meta:
        model = AIProject
        fields = ["organization", "slug", "name", "owner", "risk_level", "status"]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = admin_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["organization"]).queryset = _scope(
            Organization.objects.all(), ids
        )
        memberships = OrganizationMembership.objects.select_related("organization", "user")
        if ids is not None:
            memberships = memberships.filter(organization_id__in=ids)
        owner_organizations: dict[str, set[str]] = {}
        for membership in memberships:
            username = membership.user.get_username()
            owner_organizations.setdefault(username, set()).add(membership.organization.slug)
        cast(forms.ChoiceField, self.fields["owner"]).choices = [
            ("", "---------"),
            *[
                (username, f"{username} ({', '.join(sorted(organizations))})")
                for username, organizations in sorted(owner_organizations.items())
            ],
        ]

    def clean(self) -> dict[str, Any] | None:
        cleaned_data = super().clean()
        if cleaned_data is None:
            return None
        organization = cleaned_data.get("organization")
        owner = cleaned_data.get("owner")
        if (
            organization
            and owner
            and not OrganizationMembership.objects.filter(
                organization=organization, user__username=owner
            ).exists()
        ):
            self.add_error("owner", "Selected owner is not a member of this organization.")
        return cleaned_data


class ScenarioForm(forms.ModelForm):
    alias = forms.SlugField(
        required=False, max_length=128, help_text="Optional stable external alias."
    )

    class Meta:
        model = Scenario
        fields = ["project", "slug", "name", "type", "visibility", "risk_level", "status"]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = author_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["project"]).queryset = _scope(
            AIProject.objects.select_related("organization"), ids, "organization_id"
        )

    def clean_alias(self) -> str:
        alias = self.cleaned_data["alias"]
        project = self.cleaned_data.get("project")
        if (
            alias
            and project
            and ScenarioAlias.objects.filter(
                organization_id=project.organization_id, alias=alias
            ).exists()
        ):
            raise forms.ValidationError("This alias already exists in the organization.")
        return alias


class ConsumerForm(forms.ModelForm):
    class Meta:
        model = Consumer
        fields = ["organization", "subject", "name", "protocol", "status"]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = admin_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["organization"]).queryset = _scope(
            Organization.objects.all(), ids
        )


class BindingForm(forms.ModelForm):
    capabilities = forms.MultipleChoiceField(
        choices=Capability.choices, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = ConsumerBinding
        fields = ["consumer", "scenario", "status"]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = admin_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["consumer"]).queryset = _scope(
            Consumer.objects.select_related("organization"), ids, "organization_id"
        )
        cast(forms.ModelChoiceField, self.fields["scenario"]).queryset = _scope(
            Scenario.objects.select_related("project"), ids, "project__organization_id"
        )

    def save(self, commit: bool = True) -> ConsumerBinding:
        instance = super().save(commit=False)
        instance.capabilities = list(self.cleaned_data["capabilities"])
        if commit:
            instance.save()  # full_clean() runs here: capability allowlist + cross-org
        return instance


class CanaryForm(forms.Form):
    """Start-canary form: pick a consumer in the release's org and a bounded lifetime."""

    consumer = forms.ModelChoiceField(queryset=Consumer.objects.none())
    ttl_hours = forms.IntegerField(
        min_value=1, max_value=168, initial=24, label="Canary lifetime (hours)"
    )

    def __init__(self, *args: Any, release: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if release is not None:
            org_id = release.scenario.project.organization_id
            cast(
                forms.ModelChoiceField, self.fields["consumer"]
            ).queryset = Consumer.objects.filter(organization_id=org_id)
