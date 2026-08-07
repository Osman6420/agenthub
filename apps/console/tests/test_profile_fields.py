"""A governed profile is authored through fields, and the help matches the validator."""

from __future__ import annotations

import pytest

from apps.artifacts.governed_dsl import (
    CHUNKING_SIZE_MAX,
    CHUNKING_SIZE_MIN,
    CHUNKING_STRATEGIES,
    RETRIEVAL_MODES,
    RETRIEVAL_TOP_K_MAX,
    GovernedDSLValidationError,
    validate_chunking_profile,
    validate_retrieval_profile,
)
from apps.artifacts.types import ArtifactType
from apps.console.profile_fields import profile_defaults, profile_form


def _defaults(artifact_type: str) -> dict:
    return profile_defaults(artifact_type)


def test_the_offered_defaults_are_accepted_by_the_validator() -> None:
    """A form that starts invalid teaches the operator nothing."""

    validate_chunking_profile(_defaults(ArtifactType.CHUNKING_PROFILE))
    validate_retrieval_profile(_defaults(ArtifactType.RETRIEVAL_PROFILE))


def test_every_offered_choice_is_one_the_validator_allows() -> None:
    """The options only lived inside the validator, so the form has to read them from it."""

    chunking = profile_form(ArtifactType.CHUNKING_PROFILE)
    assert chunking is not None
    strategies = next(f for f in chunking["fields"] if f["name"] == "strategy")
    assert [choice["value"] for choice in strategies["choices"]] == list(CHUNKING_STRATEGIES)

    retrieval = profile_form(ArtifactType.RETRIEVAL_PROFILE)
    assert retrieval is not None
    modes = next(f for f in retrieval["fields"] if f["name"] == "mode")
    assert [choice["value"] for choice in modes["choices"]] == list(RETRIEVAL_MODES)


def test_stated_bounds_are_the_enforced_bounds() -> None:
    chunking = profile_form(ArtifactType.CHUNKING_PROFILE)
    assert chunking is not None
    size = next(f for f in chunking["fields"] if f["name"] == "size")
    assert (size["min"], size["max"]) == (CHUNKING_SIZE_MIN, CHUNKING_SIZE_MAX)

    body = _defaults(ArtifactType.CHUNKING_PROFILE)
    body["size"] = size["max"]
    body["overlap"] = 0
    validate_chunking_profile(body)
    body["size"] = size["max"] + 1
    with pytest.raises(GovernedDSLValidationError):
        validate_chunking_profile(body)

    retrieval = profile_form(ArtifactType.RETRIEVAL_PROFILE)
    assert retrieval is not None
    top_k = next(f for f in retrieval["fields"] if f["name"] == "top_k")
    assert top_k["max"] == RETRIEVAL_TOP_K_MAX


def test_hybrid_only_weights_are_marked_conditional() -> None:
    """The validator rejects weights outside hybrid, so the form must hide them there."""

    retrieval = profile_form(ArtifactType.RETRIEVAL_PROFILE)
    assert retrieval is not None
    conditional = {f["name"] for f in retrieval["fields"] if f.get("only_when")}
    assert conditional == {"vector_weight", "keyword_weight"}

    # The default mode is hybrid, which *requires* the weights, so they are in the defaults.
    assert _defaults(ArtifactType.RETRIEVAL_PROFILE).keys() >= conditional

    # Switching away from hybrid must drop them — which is exactly what the client does when
    # the field is hidden. Leaving them in place is a validator failure, not a warning.
    keyword_body = _defaults(ArtifactType.RETRIEVAL_PROFILE)
    keyword_body["mode"] = "keyword"
    with pytest.raises(GovernedDSLValidationError):
        validate_retrieval_profile(keyword_body)
    for name in conditional:
        keyword_body.pop(name)
    validate_retrieval_profile(keyword_body)


def test_every_field_carries_help_an_operator_can_act_on() -> None:
    for artifact_type in (ArtifactType.CHUNKING_PROFILE, ArtifactType.RETRIEVAL_PROFILE):
        schema = profile_form(artifact_type)
        assert schema is not None
        assert schema["summary"].strip()
        for field in schema["fields"]:
            assert field["help"].strip(), f"{artifact_type}.{field['name']} has no help"


def test_a_type_without_a_description_is_reported_as_absent() -> None:
    assert profile_form(ArtifactType.WORKFLOW_DEFINITION) is None
