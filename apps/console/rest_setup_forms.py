"""REST setup presentation; canonical contract validation remains in ingestion."""

from __future__ import annotations

import json
from typing import Any, cast

from django import forms

from apps.console.forms import BoundedJsonField
from apps.ingestion.models import RestPullProfile, TenantRestPullProfileGrant
from apps.ingestion.rest_schema import RestContractError, validate_contract, validate_source_inputs
from apps.ingestion.rest_setup_schedule import preparation_fingerprint


class RestProfileChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.logical_id} · r{obj.revision} · {obj.method}"


class ConnectionStep(forms.Form):
    name = forms.CharField(max_length=200, label="Kaynak adı")
    profile = RestProfileChoice(
        queryset=RestPullProfile.objects.none(), to_field_name="public_id", label="Onaylı bağlantı"
    )

    def __init__(self, *args, document_set, allow_unselected=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile"].required = not allow_unselected
        grants = (
            TenantRestPullProfileGrant.objects.filter(
                organization_id=document_set.organization_id,
                document_set=document_set,
                rest_profile__status="active",
            )
            .order_by("rest_profile__logical_id", "-rest_profile__revision")
            .values("rest_profile_id")[:200]
        )
        cast(
            forms.ModelChoiceField, self.fields["profile"]
        ).queryset = RestPullProfile.objects.filter(pk__in=grants).order_by(
            "logical_id", "-revision"
        )


class MappingStep(forms.Form):
    path = forms.CharField(max_length=1024, label="Belge listesinin yolu", initial="/documents")
    items_pointer = forms.CharField(
        max_length=512, required=False, initial="/items", label="Belge listesi alanı"
    )
    id_pointer = forms.CharField(
        max_length=512, required=False, initial="/id", label="Belge kimliği alanı"
    )
    title_enabled = forms.BooleanField(required=False, initial=True, label="Başlık alanı var")
    title_pointer = forms.CharField(
        max_length=512, required=False, initial="/title", label="Başlık alanı"
    )
    revision_enabled = forms.BooleanField(required=False, label="Sürüm alanı var")
    revision_pointer = forms.CharField(max_length=512, required=False, label="Sürüm alanı")
    deleted_enabled = forms.BooleanField(required=False, label="Silinme bilgisi alanı var")
    deleted_pointer = forms.CharField(max_length=512, required=False, label="Silinme bilgisi alanı")
    content_pointer = forms.CharField(
        max_length=512, required=False, initial="/content", label="İçerik alanı"
    )
    content_encoding = forms.ChoiceField(
        choices=[("utf8_text", "Metin"), ("base64", "Base64")], label="İçerik biçimi"
    )
    mime_type = forms.CharField(max_length=128, initial="text/plain", label="Belge türü (MIME)")
    detail_enabled = forms.BooleanField(required=False, label="İçerik ayrı belge isteğinden alınır")
    detail_path = forms.CharField(
        max_length=512, required=False, label="Ayrı belge yolu ({input:id} kullanılabilir)"
    )
    pagination = forms.ChoiceField(
        choices=[
            ("none", "Tek yanıt"),
            ("page_number", "Sayfa numarası"),
            ("offset", "Başlangıç sırası"),
            ("cursor", "Devam anahtarı"),
        ],
        label="Sayfalama",
    )
    parameter = forms.CharField(max_length=64, required=False, label="Sayfalama parametresi")
    page_size = forms.IntegerField(
        min_value=1, max_value=1000, required=False, label="Sayfadaki belge sayısı"
    )
    cursor_pointer = forms.CharField(max_length=512, required=False, label="Devam anahtarı alanı")
    query_enabled = forms.BooleanField(required=False, label="Sorgu parametreleri kullan")
    query = BoundedJsonField(
        max_length=32000, max_depth=16, required=False, label="Sorgu parametreleri", initial="{}"
    )
    body_enabled = forms.BooleanField(required=False, label="POST istek gövdesi kullan")
    body = BoundedJsonField(
        max_length=32000, max_depth=16, required=False, label="İstek gövdesi", initial="{}"
    )
    inputs_schema = BoundedJsonField(
        max_length=32000, max_depth=16, required=False, label="Değişken tanımları", initial="{}"
    )

    def __init__(self, *args, method, **kwargs):
        self.method = method
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                "path",
                "items_pointer",
                "id_pointer",
                "title_enabled",
                "title_pointer",
                "content_pointer",
                "content_encoding",
                "mime_type",
                "revision_enabled",
                "revision_pointer",
                "deleted_enabled",
                "deleted_pointer",
                "detail_enabled",
                "detail_path",
                "pagination",
                "parameter",
                "page_size",
                "cursor_pointer",
                "query_enabled",
                "query",
                "body_enabled",
                "body",
                "inputs_schema",
            ]
        )

    def clean(self):
        data = super().clean() or {}
        if self.errors:
            return data
        request: dict[str, Any] = {"method": self.method, "path": data["path"]}
        for field in ("query", "body"):
            if data[f"{field}_enabled"]:
                request[field] = data[field]
        response = {
            key: data[key]
            for key in ("items_pointer", "id_pointer", "content_encoding", "mime_type")
        }
        for field in ("title", "revision", "deleted"):
            if data[f"{field}_enabled"]:
                response[f"{field}_pointer"] = data[f"{field}_pointer"]
        if data["detail_enabled"]:
            response["detail"] = {
                "path": data["detail_path"],
                "content_pointer": data["content_pointer"],
            }
        else:
            response["content_pointer"] = data["content_pointer"]
        pagination = {"mode": data["pagination"]}
        if data["pagination"] != "none":
            pagination.update(parameter=data["parameter"], page_size=data["page_size"])
        if data["pagination"] == "cursor":
            pagination["cursor_pointer"] = data["cursor_pointer"]
        try:
            self.definition = validate_contract(
                {
                    "version": 1,
                    "inputs": data["inputs_schema"] if data["inputs_schema"] is not None else {},
                    "request": request,
                    "response": response,
                    "pagination": pagination,
                }
            )
        except RestContractError as exc:
            raise forms.ValidationError(f"Eşlemeyi kontrol edin: {exc.code}") from None
        return data


class AdvancedMappingStep(forms.Form):
    definition = BoundedJsonField(
        max_length=100000, max_depth=16, label="REST veri eşlemesi (JSON)"
    )

    def clean_definition(self):
        try:
            return validate_contract(self.cleaned_data["definition"])
        except RestContractError as exc:
            raise forms.ValidationError(f"Eşlemeyi kontrol edin: {exc.code}") from None


def visual_initial(definition):
    """Project all supported fields and refuse any lossy advanced-to-form switch."""
    definition = validate_contract(definition)
    request, response, pagination = (
        definition[key] for key in ("request", "response", "pagination")
    )
    values = {
        "path": request["path"],
        "inputs_schema": json.dumps(definition["inputs"]),
        "pagination": pagination["mode"],
    }
    for key in ("items_pointer", "id_pointer", "content_encoding", "mime_type"):
        values[key] = response[key]
    for field in ("title", "revision", "deleted"):
        values[f"{field}_enabled"] = f"{field}_pointer" in response
        values[f"{field}_pointer"] = response.get(f"{field}_pointer", "")
    detail = response.get("detail")
    values["detail_enabled"] = detail is not None
    values["detail_path"] = detail["path"] if detail else ""
    values["content_pointer"] = detail["content_pointer"] if detail else response["content_pointer"]
    for field in ("query", "body"):
        values[f"{field}_enabled"] = field in request
        values[field] = json.dumps(request.get(field, {}))
    for key in ("parameter", "page_size", "cursor_pointer"):
        values[key] = pagination.get(key, "")
    probe = MappingStep(values, method=request["method"])
    if not probe.is_valid() or probe.definition != definition:
        raise RestContractError("REST_VISUAL_ROUND_TRIP_UNSUPPORTED")
    return values


class InputStep(forms.Form):
    sync_mode = forms.ChoiceField(
        required=False,
        initial="manual",
        label="Belgeler ne zaman alınsın?",
        choices=[("manual", "Ben başlattığımda"), ("periodic", "Belirli aralıklarla")],
    )
    interval_seconds = forms.TypedChoiceField(
        required=False,
        initial=86400,
        coerce=int,
        label="Yenileme aralığı",
        choices=[
            (900, "15 dakika"),
            (3600, "1 saat"),
            (21600, "6 saat"),
            (86400, "24 saat"),
            (604800, "7 gün"),
        ],
    )
    preparation_mode = forms.ChoiceField(
        required=False,
        initial="draft_only",
        label="Periyodik yenilemeden sonra ne yapılsın?",
        choices=[
            ("draft_only", "Belgeleri taslakta tut"),
            ("stage_only", "Doküman setinin ayarlarıyla aramaya hazırla"),
        ],
    )

    def __init__(
        self, *args, definition, preparation_policy=None, publication_targets=None, **kwargs
    ):
        self.definition = validate_contract(definition)
        self.preparation_policy = preparation_policy
        self.publication_targets = publication_targets
        super().__init__(*args, **kwargs)
        if publication_targets:
            mode = self.fields["preparation_mode"]
            if not isinstance(mode, forms.ChoiceField):
                raise TypeError("Preparation mode must be a choice field")
            mode.choices = [
                ("draft_only", "Belgeleri taslakta tut"),
                ("stage_only", "Doküman setinin ayarlarıyla aramaya hazırla"),
                ("promote_if_safe", "Testlerden sonra mevcut onaylı senaryolarda yayınla"),
            ]
        for name, spec in self.definition["inputs"].items():
            key = f"input_{name}"
            field: forms.Field
            match spec["type"]:
                case "string":
                    field = forms.CharField(
                        max_length=spec["max_length"], required=False, strip=False
                    )
                case "integer":
                    field = forms.IntegerField(min_value=spec["minimum"], max_value=spec["maximum"])
                case "boolean":
                    field = forms.TypedChoiceField(
                        choices=[("true", "Evet"), ("false", "Hayır")],
                        coerce=lambda value: value == "true",
                    )
                case "enum":
                    field = forms.ChoiceField(choices=[(value, value) for value in spec["values"]])
            field.label = name
            self.fields[key] = field

    def clean(self):
        data = super().clean() or {}
        self.schedule: dict[str, Any] | None = None
        if data.get("sync_mode") == "periodic":
            if not data.get("interval_seconds"):
                self.add_error("interval_seconds", "Yenileme aralığını seçin.")
            else:
                self.schedule = {"interval_seconds": data["interval_seconds"]}
        if data.get("preparation_mode") in {"stage_only", "promote_if_safe"}:
            if data.get("sync_mode") != "periodic":
                self.add_error("preparation_mode", "Bu seçenek için periyodik yenilemeyi seçin.")
            elif self.preparation_policy is None:
                self.add_error(
                    "preparation_mode",
                    "Doküman setinin geçerli hazırlama ayarları ve model izinleri gerekiyor.",
                )
            elif self.schedule is not None:
                self.schedule["preparation"] = preparation_fingerprint(self.preparation_policy)
                if data.get("preparation_mode") == "promote_if_safe":
                    self.schedule["publication_targets"] = list(self.publication_targets)
        if not self.errors:
            try:
                self.inputs = validate_source_inputs(
                    self.definition,
                    {name: data[f"input_{name}"] for name in self.definition["inputs"]},
                )
            except RestContractError:
                raise forms.ValidationError("Değişken değerlerini kontrol edin.") from None
        return data
