from __future__ import annotations

import json
from typing import Any, cast

from django import forms

from apps.evaluations.question_services import QuestionEvaluationError, normalize_cases


class QuestionSetDraftForm(forms.Form):
    name = forms.CharField(max_length=200, label="Soru seti adı")
    description = forms.CharField(
        max_length=1000,
        required=False,
        label="Açıklama",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    cases_json = forms.CharField(
        label="Vakalar (JSON)",
        widget=forms.Textarea(attrs={"rows": 18, "spellcheck": "false"}),
        help_text=(
            "Her vaka id, question ve isteğe bağlı input, assertions, expected_anchors, judge "
            "alanlarını taşır."
        ),
    )
    expected_revision = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)

    def clean_cases_json(self) -> list[dict[str, object]]:
        try:
            value = json.loads(self.cleaned_data["cases_json"])
            return normalize_cases(value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("Geçerli JSON girin.") from exc
        except QuestionEvaluationError as exc:
            raise forms.ValidationError(exc.code) from exc


class EvaluationTargetForm(forms.Form):
    question_set_version = forms.ChoiceField(label="Yayımlanmış soru seti sürümü")
    target = forms.ChoiceField(label="Exact hedef")
    idempotency_key = forms.CharField(max_length=128, widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        version_choices: list[tuple[str, str]],
        target_choices: list[tuple[str, str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        version_field = cast(forms.ChoiceField, self.fields["question_set_version"])
        target_field = cast(forms.ChoiceField, self.fields["target"])
        version_field.choices = version_choices
        target_field.choices = target_choices


class OneOffQuestionForm(forms.Form):
    question = forms.CharField(
        max_length=4000,
        label="Soru",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
