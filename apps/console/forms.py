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
from apps.tenancy.models import Organization
from apps.tenancy.services import admin_organization_ids, author_organization_ids


def _scope(qs: QuerySet, ids: set[int] | None, field: str = "id") -> QuerySet:
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["slug", "name", "status"]


class ProjectForm(forms.ModelForm):
    class Meta:
        model = AIProject
        fields = ["organization", "slug", "name", "owner", "risk_level", "status"]

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = admin_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["organization"]).queryset = _scope(
            Organization.objects.all(), ids
        )


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
