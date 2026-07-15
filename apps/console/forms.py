"""Console authoring forms.

Each form scopes its foreign-key choices to what the operator may administer/author,
so the UI cannot offer a parent org/project outside the user's scope. Views re-check
authorization server-side before saving (defense in depth).
"""

from __future__ import annotations

import json
from typing import Any, cast

from django import forms
from django.db.models import QuerySet

from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.documents.models import DocumentSet, ScenarioDocumentSetBinding
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding
from apps.ingestion.models import (
    ConfluenceProfile,
    ConfluenceProfileStatus,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    OcrProfile,
    OcrProfileStatus,
    RestPullContract,
    RestPullContractStatus,
    RestPullProfile,
    RestPullProfileStatus,
    ScheduleAutomationMode,
    TenantConfluenceProfileGrant,
    TenantRestPullProfileGrant,
)
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus
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
            Organization.objects.filter(status=OrganizationStatus.ACTIVE), ids
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
            AIProject.objects.select_related("organization").filter(
                organization__status=OrganizationStatus.ACTIVE
            ),
            ids,
            "organization_id",
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
            Organization.objects.filter(status=OrganizationStatus.ACTIVE), ids
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
            Consumer.objects.select_related("organization").filter(
                organization__status=OrganizationStatus.ACTIVE
            ),
            ids,
            "organization_id",
        )
        cast(forms.ModelChoiceField, self.fields["scenario"]).queryset = _scope(
            Scenario.objects.select_related("project").filter(
                project__organization__status=OrganizationStatus.ACTIVE
            ),
            ids,
            "project__organization_id",
        )

    def save(self, commit: bool = True) -> ConsumerBinding:
        instance = super().save(commit=False)
        instance.capabilities = list(self.cleaned_data["capabilities"])
        if commit:
            instance.save()  # full_clean() runs here: capability allowlist + cross-org
        return instance


class DocumentUploadForm(forms.Form):
    """Upload a document into an author-scoped organization (P8.1).

    The organization choices are limited to orgs the operator may author in; the view re-checks
    ``can_author_scenarios`` server-side before storing (defense in depth). The MIME type is taken
    from the uploaded file in the view and validated by the document service's allowlist.
    """

    organization = forms.ModelChoiceField(queryset=Organization.objects.none())
    logical_id = forms.SlugField(
        max_length=128, help_text="Stable per-tenant document id (new version on re-upload)."
    )
    title = forms.CharField(max_length=500, required=False)
    file = forms.FileField()

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = author_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["organization"]).queryset = _scope(
            Organization.objects.filter(status=OrganizationStatus.ACTIVE), ids
        )


class DocumentSetForm(forms.Form):
    """Create a document set in an author-scoped organization (P8.2)."""

    organization = forms.ModelChoiceField(queryset=Organization.objects.none())
    logical_id = forms.SlugField(max_length=128)
    name = forms.CharField(max_length=200)

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = author_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["organization"]).queryset = _scope(
            Organization.objects.filter(status=OrganizationStatus.ACTIVE), ids
        )


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("widget", MultipleFileInput(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data: Any, initial: Any = None) -> list[Any]:
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_one(item, initial) for item in data]
        return [clean_one(data, initial)]


class DocumentSetBulkUploadForm(forms.Form):
    uploads = MultipleFileField(label="Dosyalar")


class DocumentSetBuildForm(forms.Form):
    embedding_profile = forms.ModelChoiceField(
        queryset=EmbeddingProfile.objects.none(), label="Embedding profili"
    )
    ocr_profile = forms.ModelChoiceField(
        queryset=OcrProfile.objects.none(), required=False, label="OCR profili (isteğe bağlı)"
    )

    def __init__(self, *args: Any, organization_id: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(
            forms.ModelChoiceField, self.fields["embedding_profile"]
        ).queryset = EmbeddingProfile.objects.filter(
            status=EmbeddingProfileStatus.ACTIVE,
            tenant_grants__organization_id=organization_id,
        ).distinct()
        cast(
            forms.ModelChoiceField, self.fields["ocr_profile"]
        ).queryset = OcrProfile.objects.filter(
            status=OcrProfileStatus.ACTIVE,
            tenant_grants__organization_id=organization_id,
        ).distinct()


class BoundedJsonField(forms.CharField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("widget", forms.Textarea(attrs={"rows": 12, "class": "mono"}))
        super().__init__(*args, **kwargs)

    def clean(self, value: Any) -> Any:
        raw = super().clean(value)
        if raw in self.empty_values:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise forms.ValidationError("Geçerli bir JSON değeri girin.") from exc


def _page_ids(value: str) -> list[str]:
    return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]


class ConfluenceSourceForm(forms.Form):
    confluence_profile = forms.ModelChoiceField(
        queryset=ConfluenceProfile.objects.none(), label="Confluence profili"
    )
    slug = forms.SlugField(max_length=64, label="Kaynak ID")
    name = forms.CharField(max_length=200, label="Kaynak adı")
    root_page_ids = forms.CharField(
        max_length=3_500,
        label="Kök sayfa ID'leri",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Her satıra bir sayfa ID'si; en fazla 50.",
    )
    excluded_page_ids = forms.CharField(
        max_length=35_000,
        required=False,
        label="Hariç tutulan sayfa ID'leri",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    include_root = forms.BooleanField(required=False, initial=True, label="Kök sayfaları dahil et")

    def __init__(self, *args: Any, document_set: DocumentSet, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        profile_ids = TenantConfluenceProfileGrant.objects.filter(
            organization_id=document_set.organization_id, document_set=document_set
        ).values_list("confluence_profile_id", flat=True)
        cast(
            forms.ModelChoiceField, self.fields["confluence_profile"]
        ).queryset = ConfluenceProfile.objects.filter(
            pk__in=profile_ids, status=ConfluenceProfileStatus.ACTIVE
        ).order_by("logical_id", "-revision")

    def clean_root_page_ids(self) -> list[str]:
        return _page_ids(self.cleaned_data["root_page_ids"])

    def clean_excluded_page_ids(self) -> list[str]:
        return _page_ids(self.cleaned_data["excluded_page_ids"])


class RestContractForm(forms.Form):
    logical_id = forms.SlugField(max_length=128, label="Sözleşme ID")
    revision = forms.IntegerField(min_value=1, label="Revizyon")
    definition = BoundedJsonField(max_length=200_000, label="Kapalı REST mapping sözleşmesi")
    synthetic_response = BoundedJsonField(
        max_length=1_000_000,
        required=False,
        label="Sentetik response (isteğe bağlı preview)",
    )

    def clean_definition(self) -> dict[str, Any]:
        value = self.cleaned_data["definition"]
        if not isinstance(value, dict):
            raise forms.ValidationError("Sözleşme bir JSON object olmalıdır.")
        return value


class RestSourceForm(forms.Form):
    rest_profile = forms.ModelChoiceField(
        queryset=RestPullProfile.objects.none(), label="REST hedef profili"
    )
    rest_contract = forms.ModelChoiceField(
        queryset=RestPullContract.objects.none(), label="Mapping sözleşmesi"
    )
    slug = forms.SlugField(max_length=64, label="Kaynak ID")
    name = forms.CharField(max_length=200, label="Kaynak adı")
    inputs = BoundedJsonField(max_length=64_000, label="Sözleşme input değerleri")

    def __init__(self, *args: Any, document_set: DocumentSet, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        profile_ids = TenantRestPullProfileGrant.objects.filter(
            organization_id=document_set.organization_id, document_set=document_set
        ).values_list("rest_profile_id", flat=True)
        cast(
            forms.ModelChoiceField, self.fields["rest_profile"]
        ).queryset = RestPullProfile.objects.filter(
            pk__in=profile_ids, status=RestPullProfileStatus.ACTIVE
        ).order_by("logical_id", "-revision")
        cast(
            forms.ModelChoiceField, self.fields["rest_contract"]
        ).queryset = RestPullContract.objects.filter(
            organization_id=document_set.organization_id,
            status=RestPullContractStatus.ACTIVE,
        ).order_by("logical_id", "-revision")

    def clean_inputs(self) -> dict[str, Any]:
        value = self.cleaned_data["inputs"]
        if not isinstance(value, dict):
            raise forms.ValidationError("Input değerleri bir JSON object olmalıdır.")
        return value


class ConnectorScheduleForm(forms.Form):
    interval_seconds = forms.TypedChoiceField(
        coerce=int,
        choices=[
            (900, "15 dakika"),
            (3_600, "1 saat"),
            (21_600, "6 saat"),
            (86_400, "24 saat"),
            (604_800, "7 gün"),
        ],
        label="Yenileme aralığı",
    )
    enabled = forms.BooleanField(required=False, label="Periyodik yenilemeyi etkinleştir")
    automation_mode = forms.ChoiceField(
        choices=ScheduleAutomationMode.choices, label="Değişiklik sonrası işlem"
    )
    embedding_profile = forms.ModelChoiceField(
        queryset=EmbeddingProfile.objects.none(), required=False, label="Embedding profili"
    )
    scenarios = forms.ModelMultipleChoiceField(
        queryset=Scenario.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Otomatik promotion senaryoları",
    )

    def __init__(
        self,
        *args: Any,
        document_set: DocumentSet,
        allow_authoring: bool,
        allow_promotion: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ModelChoiceField, self.fields["embedding_profile"]).queryset = (
            EmbeddingProfile.objects.filter(
                status=EmbeddingProfileStatus.ACTIVE,
                tenant_grants__organization_id=document_set.organization_id,
            )
            .distinct()
            .order_by("logical_id", "-revision")
        )
        scenario_ids = ScenarioDocumentSetBinding.objects.filter(
            organization_id=document_set.organization_id, document_set=document_set
        ).values_list("scenario_id", flat=True)
        cast(forms.ModelMultipleChoiceField, self.fields["scenarios"]).queryset = (
            Scenario.objects.filter(pk__in=scenario_ids)
            .select_related("project")
            .order_by("project__slug", "slug")
        )
        choices = list(ScheduleAutomationMode.choices)
        if not allow_authoring:
            choices = [
                choice for choice in choices if choice[0] == ScheduleAutomationMode.PROMOTE_IF_SAFE
            ]
        elif not allow_promotion:
            choices = [
                choice for choice in choices if choice[0] != ScheduleAutomationMode.PROMOTE_IF_SAFE
            ]
        cast(forms.ChoiceField, self.fields["automation_mode"]).choices = choices


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
