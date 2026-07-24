"""Console authoring forms.

Each form scopes its foreign-key choices to what the operator may administer/author,
so the UI cannot offer a parent org/project outside the user's scope. Views re-check
authorization server-side before saving (defense in depth).
"""

from __future__ import annotations

import json
from typing import Any, cast

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet, ScenarioDocumentSetBinding
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding
from apps.identity.roles import Role
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

APPLICATION_MEMBERSHIP_ROLE_CHOICES = [
    choice
    for choice in Role.choices
    if choice[0] in {Role.ORGANIZATION_ADMIN, Role.APPROVER, Role.AUDITOR}
]


def _scope(qs: QuerySet, ids: set[int] | None, field: str = "id") -> QuerySet:
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "status"]
        labels = {"name": "Organizasyon adı", "status": "Yaşam döngüsü durumu"}
        help_texts = {"name": "Kalıcı teknik kimlik otomatik oluşturulur."}

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)


class ProjectOwnerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, membership: OrganizationMembership) -> str:
        return (
            f"{membership.user.get_username()} · {membership.organization.name} · "
            f"{membership.get_role_display()}"
        )


class ProjectForm(forms.ModelForm):
    owner_membership = ProjectOwnerChoiceField(
        queryset=OrganizationMembership.objects.none(),
        label="Proje sahibi",
        help_text="Yalnız seçilen organizasyonun yönetici veya proje sahibi üyeleri atanabilir.",
    )

    class Meta:
        model = AIProject
        fields = ["name", "owner_membership", "risk_level", "status"]
        labels = {"name": "Proje adı"}
        help_texts = {"name": "Kalıcı proje kimliği otomatik oluşturulur."}

    def __init__(
        self, *args: Any, user: Any = None, organization: Organization | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        memberships = OrganizationMembership.objects.select_related("organization", "user").filter(
            organization__status=OrganizationStatus.ACTIVE,
            role__in=[Role.ORGANIZATION_ADMIN, Role.PROJECT_OWNER],
        )
        memberships = (
            memberships.filter(organization=organization)
            if organization is not None
            else memberships.none()
        )
        cast(
            forms.ModelChoiceField, self.fields["owner_membership"]
        ).queryset = memberships.order_by("organization__name", "user__username")

    def clean(self) -> dict[str, Any] | None:
        cleaned_data = super().clean()
        if cleaned_data is None:
            return None
        owner_membership = cleaned_data.get("owner_membership")
        owner_queryset = cast(forms.ModelChoiceField, self.fields["owner_membership"]).queryset
        if owner_membership and (
            owner_queryset is None or not owner_queryset.filter(pk=owner_membership.pk).exists()
        ):
            self.add_error(
                "owner_membership", "Seçilen proje sahibi bu organizasyonun uygun bir üyesi değil."
            )
        return cleaned_data


class ScenarioForm(forms.ModelForm):
    class Meta:
        model = Scenario
        fields = ["name", "type", "visibility", "risk_level", "status"]
        labels = {"name": "Senaryo adı"}
        help_texts = {"name": "Kalıcı kimlik ve ilk API alias'ı otomatik oluşturulur."}

    def __init__(
        self,
        *args: Any,
        user: Any = None,
        project: AIProject | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)


class ConsumerForm(forms.ModelForm):
    class Meta:
        model = Consumer
        fields = ["name", "protocol", "status"]
        labels = {"name": "İstemci uygulama adı", "protocol": "Protokol"}
        help_texts = {
            "name": "Bearer kimlik konusu sistem tarafından güvenli ve kalıcı olarak oluşturulur.",
            "protocol": "Kimlik bilgisi, istemci oluşturulduktan sonra ayrı olarak üretilir.",
        }

    def __init__(
        self, *args: Any, user: Any = None, organization: Organization | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)


class MembershipCreateForm(forms.Form):
    user = forms.CharField(
        max_length=150,
        label="Kullanıcı adı",
        help_text="Mevcut ve etkin directory kullanıcısının tam kullanıcı adını girin.",
        strip=True,
    )
    role = forms.ChoiceField(
        choices=APPLICATION_MEMBERSHIP_ROLE_CHOICES,
        label="Rol",
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_user(self) -> Any:
        username = self.cleaned_data["user"]
        user = get_user_model().objects.filter(username=username, is_active=True).first()
        if (
            user is None
            or OrganizationMembership.objects.filter(
                organization=self.organization, user=user
            ).exists()
        ):
            raise forms.ValidationError("Kullanıcı eklenemiyor.")
        return user


class MembershipRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=APPLICATION_MEMBERSHIP_ROLE_CHOICES,
        label="Rol",
    )


class AssignmentMemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, membership: OrganizationMembership) -> str:
        return membership.user.get_username()


class DelegatedAssignmentForm(forms.Form):
    PROJECT_ADMINISTRATOR = "project_administrator"
    SCENARIO_EDITOR = "scenario_editor"
    DOCUMENT_SET_MANAGER = "document_set_manager"

    responsibility = forms.ChoiceField(
        choices=[
            (PROJECT_ADMINISTRATOR, "Project Administrator"),
            (SCENARIO_EDITOR, "Scenario Editor"),
            (DOCUMENT_SET_MANAGER, "Document Set Manager"),
        ],
        label="Sorumluluk",
    )
    member = AssignmentMemberChoiceField(
        queryset=OrganizationMembership.objects.none(),
        label="Organizasyon üyesi",
    )
    project = forms.ModelChoiceField(
        queryset=AIProject.objects.none(),
        required=False,
        label="Proje",
    )
    scenario = forms.ModelChoiceField(
        queryset=Scenario.objects.none(),
        required=False,
        label="Senaryo",
    )
    document_set = forms.ModelChoiceField(
        queryset=DocumentSet.objects.none(),
        required=False,
        label="Doküman seti",
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ModelChoiceField, self.fields["member"]).queryset = (
            OrganizationMembership.objects.select_related("user")
            .filter(
                organization=organization,
                user__is_active=True,
                user__is_superuser=False,
            )
            .order_by("user__username")
        )
        cast(forms.ModelChoiceField, self.fields["project"]).queryset = AIProject.objects.filter(
            organization=organization
        ).order_by("name", "slug")
        cast(forms.ModelChoiceField, self.fields["scenario"]).queryset = Scenario.objects.filter(
            project__organization=organization
        ).order_by("project__name", "name", "slug")
        cast(
            forms.ModelChoiceField, self.fields["document_set"]
        ).queryset = DocumentSet.objects.filter(organization=organization).order_by(
            "name", "logical_id"
        )

    def clean(self) -> dict[str, Any] | None:
        cleaned_data = super().clean()
        if cleaned_data is None:
            return None
        responsibility = cleaned_data.get("responsibility")
        if not isinstance(responsibility, str):
            return cleaned_data
        target_field = {
            self.PROJECT_ADMINISTRATOR: "project",
            self.SCENARIO_EDITOR: "scenario",
            self.DOCUMENT_SET_MANAGER: "document_set",
        }.get(responsibility)
        if target_field is None:
            return cleaned_data
        target = cleaned_data.get(target_field)
        if target is None:
            self.add_error(target_field, "Seçilen sorumluluk için hedef zorunludur.")
        cleaned_data["target"] = target
        return cleaned_data


class ConsumerTokenIssueForm(forms.Form):
    name = forms.CharField(
        max_length=200,
        label="Token adı",
        help_text="Örneğin: üretim, test veya entegrasyon adı. Gizli değer burada saklanmaz.",
        strip=True,
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
    title = forms.CharField(max_length=500, required=False, label="Başlık")
    file = forms.FileField(label="Dosya", help_text="Kalıcı doküman kimliği otomatik oluşturulur.")

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = author_organization_ids(user)
        cast(forms.ModelChoiceField, self.fields["organization"]).queryset = _scope(
            Organization.objects.filter(status=OrganizationStatus.ACTIVE), ids
        )


class DocumentSetForm(forms.Form):
    """Create a document set in an author-scoped organization (P8.2)."""

    name = forms.CharField(
        max_length=200,
        label="Doküman seti adı",
        help_text="Kalıcı doküman seti kimliği otomatik oluşturulur.",
    )

    def __init__(
        self, *args: Any, user: Any = None, organization: Organization | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)


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


class DocumentReplacementForm(forms.Form):
    file = forms.FileField(
        label="Yeni dosya",
        help_text="Yeni immutable sürüm oluşturulur; mevcut kimlik korunur.",
    )


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
