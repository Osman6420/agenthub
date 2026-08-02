from __future__ import annotations

import json

import pytest
from django.test import override_settings

from apps.builder.authoring import parse_candidate, validate_description
from apps.builder.services import BuilderError


def test_candidate_parser_accepts_json_fence_and_rejects_malformed_or_non_object() -> None:
    assert parse_candidate('{"kind":"Workflow"}')["kind"] == "Workflow"
    assert parse_candidate('```json\n{"kind":"Workflow"}\n```')["kind"] == "Workflow"
    assert parse_candidate('```JSON\r\n{"kind":"Workflow"}\r\n```')["kind"] == "Workflow"
    for value, code in [
        ("not-json", "candidate_invalid_json"),
        ("Here is JSON:\n```json\n{}\n```", "candidate_invalid_json"),
        ("```python\n{}\n```", "candidate_invalid_json"),
        ("```json\n{}\n```\n```json\n{}\n```", "candidate_invalid_json"),
        ("[]", "candidate_not_object"),
    ]:
        with pytest.raises(BuilderError, match=code):
            parse_candidate(value)


@override_settings(AI_AUTHORING_MAX_JSON_DEPTH=2)
def test_candidate_parser_rejects_deep_output() -> None:
    with pytest.raises(BuilderError, match="candidate_too_deep"):
        parse_candidate(json.dumps({"a": {"b": {"c": 1}}}))


@override_settings(AI_AUTHORING_MAX_CANDIDATE_BYTES=8)
def test_candidate_parser_rejects_oversized_output() -> None:
    with pytest.raises(BuilderError, match="candidate_too_large"):
        parse_candidate('{"long":"value"}')


@override_settings(AI_AUTHORING_MAX_DESCRIPTION_BYTES=8)
def test_description_rejects_empty_control_and_oversized_input() -> None:
    cases = [
        ("", "description_required"),
        ("x\x00", "description_invalid"),
        ("123456789", "description_too_large"),
    ]
    for value, code in cases:
        with pytest.raises(BuilderError, match=code):
            validate_description(value)
