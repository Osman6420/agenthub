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

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet, ScenarioDocumentSetBinding
from apps.identity.capabilities import Capability
from apps.identity.models import (
    Consumer,
    ConsumerBinding,
    DocumentSetResponsibility,
    OrganizationResponsibility,
    ProjectResponsibility,
    ScenarioResponsibility,
)
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
from apps.tenancy.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.tenancy.services import admin_organization_ids, author_organization_ids


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


class ProjectForm(forms.ModelForm):
    class Meta:
        model = AIProject
        fields = ["name", "risk_level", "status"]
        labels = {"name": "Proje adı"}
        help_texts = {"name": "Kalıcı proje kimliği otomatik oluşturulur."}

    def __init__(
        self, *args: Any, user: Any = None, organization: Organization | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)


SCENARIO_PRESET_CHOICES = [
    ("empty_workflow", "Empty Workflow"),
    ("document_answer", "Document Answer"),
    ("agent_loop", "Agent Loop"),
]


class ScenarioForm(forms.ModelForm):
    preset = forms.ChoiceField(
        choices=SCENARIO_PRESET_CHOICES,
        label="Başlangıç",
        help_text="Yalnız doğrulanmış bir workflow draft oluşturur; release yayımlamaz.",
        widget=forms.RadioSelect,
    )
    logical_description = forms.CharField(
        label="Logical artifact açıklaması",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Bu workflow’un sürümler boyunca değişmeyen amacı ve yeniden kullanım bağlamı.",
    )

    class Meta:
        model = Scenario
        fields = ["name"]
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


class DirectoryUserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user: Any) -> str:
        return user.get_username()


class MembershipCreateForm(forms.Form):
    user = DirectoryUserChoiceField(
        queryset=get_user_model().objects.none(),
        label="Kullanıcı",
        help_text="Organizasyona henüz eklenmemiş etkin bir kullanıcı seçin.",
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.organization = organization
        existing_user_ids = OrganizationMembership.objects.filter(
            organization=organization,
            status=MembershipStatus.ACTIVE,
        ).values_list("user_id", flat=True)
        self.fields["user"].queryset = (
            get_user_model()
            .objects.filter(is_active=True, is_superuser=False)
            .exclude(id__in=existing_user_ids)
            .order_by("username")
        )


class AssignmentMemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, membership: OrganizationMembership) -> str:
        return membership.user.get_username()


class DelegatedAssignmentForm(forms.Form):
    responsibility = forms.ChoiceField(
        choices=(
            list(OrganizationResponsibility.choices)
            + list(ProjectResponsibility.choices)
            + list(ScenarioResponsibility.choices)
            + list(DocumentSetResponsibility.choices)
        ),
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
    expires_at = forms.DateTimeField(
        required=False,
        label="Bitiş zamanı",
        help_text="Boş bırakılırsa sorumluluk süresizdir.",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ModelChoiceField, self.fields["member"]).queryset = (
            OrganizationMembership.objects.select_related("user")
            .filter(
                organization=organization,
                status=MembershipStatus.ACTIVE,
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
        if (
            responsibility == OrganizationResponsibility.ADMINISTRATOR
            and cleaned_data.get("expires_at") is not None
        ):
            self.add_error("expires_at", "Organizasyon yöneticisi süreli atanamaz.")
        target_field = {
            ProjectResponsibility.VIEWER: "project",
            ProjectResponsibility.ADMINISTRATOR: "project",
            ScenarioResponsibility.VIEWER: "scenario",
            ScenarioResponsibility.EDITOR: "scenario",
            ScenarioResponsibility.RELEASE_MANAGER: "scenario",
            ScenarioResponsibility.RUNTIME_OPERATOR: "scenario",
            ScenarioResponsibility.APPROVER: "scenario",
            DocumentSetResponsibility.METADATA_VIEWER: "document_set",
            DocumentSetResponsibility.CONTENT_READER: "document_set",
            DocumentSetResponsibility.MANAGER: "document_set",
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
    chunking_profile = forms.ModelChoiceField(
        queryset=ArtifactVersion.objects.none(), label="Parçalama profili"
    )
    retrieval_profile = forms.ModelChoiceField(
        queryset=ArtifactVersion.objects.none(), label="Arama profili"
    )
    summary_model_profile = forms.ModelChoiceField(
        queryset=ArtifactVersion.objects.none(),
        required=False,
        label="Özet model profili (isteğe bağlı)",
    )
    summary_prompt_contract = forms.ModelChoiceField(
        queryset=ArtifactVersion.objects.none(),
        required=False,
        label="Özet prompt sözleşmesi (isteğe bağlı)",
    )
    auto_prepare = forms.BooleanField(
        required=False,
        label="Sonraki yayımlanan set sürümlerini otomatik staged hazırla",
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
        artifact_fields = {
            "chunking_profile": ArtifactType.CHUNKING_PROFILE,
            "retrieval_profile": ArtifactType.RETRIEVAL_PROFILE,
            "summary_model_profile": ArtifactType.MODEL_PROFILE,
            "summary_prompt_contract": ArtifactType.PROMPT_TEMPLATE,
        }
        for field_name, artifact_type in artifact_fields.items():
            cast(
                forms.ModelChoiceField, self.fields[field_name]
            ).queryset = ArtifactVersion.objects.filter(
                organization_id=organization_id,
                type=artifact_type,
            ).order_by("logical_id", "-version")

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if bool(cleaned.get("summary_model_profile")) != bool(
            cleaned.get("summary_prompt_contract")
        ):
            raise forms.ValidationError("Özet model ve prompt profilleri birlikte seçilmelidir.")
        return cleaned


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
