"""Unit + boundary tests for the shared restricted JSON Pointer / mapping seam (P2.6.1).

These are pure and deterministic (no database): the same parser/policy is used by the
compiler, release compiler and runtime, so proving it here proves it everywhere.
"""

from __future__ import annotations

import pytest

from apps.workflows.state_mapping import (
    MAX_MAPPING_ENTRIES,
    MAX_POINTER_LENGTH,
    MAX_POINTER_SEGMENTS,
    MappingError,
    apply_output_mapping,
    build_input_envelope,
    compile_mappings,
    parse_pointer,
)


@pytest.mark.parametrize(
    ("pointer", "segments"),
    [
        ("/input", ("input",)),
        ("/input/customer_id", ("input", "customer_id")),
        ("/branches/policy/output", ("branches", "policy", "output")),
        ("/evidence/0", ("evidence", "0")),
        ("/a~1b", ("a/b",)),  # ~1 -> "/"
        ("/a~0b", ("a~b",)),  # ~0 -> "~"
    ],
)
def test_parse_pointer_accepts_canonical_forms(pointer: str, segments: tuple[str, ...]) -> None:
    assert parse_pointer(pointer) == segments


@pytest.mark.parametrize(
    "pointer",
    [
        "",  # empty / root
        "/",  # root-only -> empty segment
        "#/input",  # URI fragment
        "input/customer",  # not absolute
        "/input/",  # trailing slash -> empty segment
        "/input//customer",  # empty segment
        "/input/*",  # wildcard
        "/**",  # recursive descent
        "/items/-",  # array append
        "/items/-1",  # negative index
        "/a~",  # dangling escape
        "/a~2",  # non-canonical escape
        "/a*b",  # embedded wildcard
        123,  # not a string
        None,
    ],
)
def test_parse_pointer_rejects_forbidden_forms(pointer: object) -> None:
    with pytest.raises(MappingError) as exc:
        parse_pointer(pointer)
    assert exc.value.code == "WORKFLOW_PATH_INVALID"


def test_parse_pointer_enforces_length_and_depth_bounds() -> None:
    too_long = "/" + "a" * (MAX_POINTER_LENGTH + 1)
    with pytest.raises(MappingError) as exc:
        parse_pointer(too_long)
    assert exc.value.code == "WORKFLOW_PATH_INVALID"
    too_deep = "/" + "/".join("s" for _ in range(MAX_POINTER_SEGMENTS + 1))
    with pytest.raises(MappingError) as exc:
        parse_pointer(too_deep)
    assert exc.value.code == "WORKFLOW_PATH_INVALID"


@pytest.mark.parametrize(
    "destination",
    [
        "/secret/api_key",
        "/tenant/id",
        "/execution/capabilities",
        "/authorization/roles",
        "/release/manifest",
        "/audit/trail",
        "/budget/tokens",
        "/status",  # server-owned run field
        "/Output/answer",  # non-canonical casing is not the canonical business root
        "/ｏｕｔｐｕｔ/x",  # fullwidth confusable of "output"
        "/unknown_root/x",  # deny by default
    ],
)
def test_output_mapping_denies_protected_and_unknown_roots(destination: str) -> None:
    with pytest.raises(MappingError) as exc:
        compile_mappings([{"from": "/input/x", "to": destination}], restrict_destination=True)
    assert exc.value.code == "WORKFLOW_PATH_PROTECTED"


def test_output_mapping_allows_business_roots() -> None:
    compiled = compile_mappings(
        [
            {"from": "/input/case", "to": "/evidence/case"},
            {"from": "/retrieval/chunks", "to": "/output/sources"},
        ],
        restrict_destination=True,
    )
    assert compiled == (
        {"from": "/input/case", "to": "/evidence/case"},
        {"from": "/retrieval/chunks", "to": "/output/sources"},
    )


def test_input_mapping_destination_is_not_namespace_restricted() -> None:
    # input_mapping targets a transient node-local envelope, so any valid pointer is allowed.
    compiled = compile_mappings(
        [{"from": "/input/rows", "to": "/items"}], restrict_destination=False
    )
    assert compiled == ({"from": "/input/rows", "to": "/items"},)


@pytest.mark.parametrize(
    "entries",
    [
        [{"from": "/input/a", "to": "/evidence/x"}, {"from": "/input/b", "to": "/evidence/x"}],
        [{"from": "/input/a", "to": "/evidence"}, {"from": "/input/b", "to": "/evidence/x"}],
        [{"from": "/input/a", "to": "/evidence/x/y"}, {"from": "/input/b", "to": "/evidence/x"}],
    ],
)
def test_output_mapping_rejects_conflicting_destinations(entries: list[dict[str, str]]) -> None:
    with pytest.raises(MappingError) as exc:
        compile_mappings(entries, restrict_destination=True)
    assert exc.value.code == "WORKFLOW_MAPPING_CONFLICT"


@pytest.mark.parametrize(
    "entries",
    [
        [],  # empty
        "notalist",
        [{"from": "/input/a"}],  # missing "to"
        [{"from": "/input/a", "to": "/evidence/x", "transform_ref": "t"}],  # extra key
        [{"from": "/input/a", "to": "/evidence/x"}] * (MAX_MAPPING_ENTRIES + 1),  # too many
    ],
)
def test_compile_mappings_rejects_malformed_lists(entries: object) -> None:
    with pytest.raises(MappingError) as exc:
        compile_mappings(entries, restrict_destination=True)
    assert exc.value.code in {"WORKFLOW_MAPPING_INVALID", "WORKFLOW_MAPPING_CONFLICT"}


def test_build_input_envelope_selects_only_declared_fields() -> None:
    state = {"input": {"case": "c1", "secret_field": "s"}, "retrieval": {"chunks": [1, 2]}}
    envelope = build_input_envelope(
        state,
        [
            {"from": "/input/case", "to": "/case_id"},
            {"from": "/retrieval/chunks", "to": "/rows"},
        ],
    )
    assert envelope == {"case_id": "c1", "rows": [1, 2]}
    assert "secret_field" not in str(envelope)


def test_build_input_envelope_missing_source_fails_closed() -> None:
    with pytest.raises(MappingError) as exc:
        build_input_envelope({"input": {}}, [{"from": "/input/missing", "to": "/x"}])
    assert exc.value.code == "WORKFLOW_MAPPING_MISSING"


def test_apply_output_mapping_is_copy_on_success_and_atomic() -> None:
    state = {"input": {"a": 1}, "evidence": {"kept": True}}
    envelope = {"result": [{"id": "x"}]}
    updated = apply_output_mapping(state, envelope, [{"from": "/result", "to": "/evidence/docs"}])
    assert updated["evidence"] == {"kept": True, "docs": [{"id": "x"}]}
    # Original state is untouched (deep copy semantics).
    assert state["evidence"] == {"kept": True}
    # A missing source aborts before any mutation.
    with pytest.raises(MappingError):
        apply_output_mapping(state, {}, [{"from": "/nope", "to": "/evidence/docs"}])
    assert state["evidence"] == {"kept": True}


def test_apply_output_mapping_type_mismatch_when_parent_not_object() -> None:
    state = {"evidence": "already-a-string"}
    with pytest.raises(MappingError) as exc:
        apply_output_mapping(
            {"evidence": {"leaf": "x"}}, {"v": 1}, [{"from": "/v", "to": "/evidence/leaf/deep"}]
        )
    assert exc.value.code == "WORKFLOW_MAPPING_TYPE_MISMATCH"
    # A protected root is re-checked at apply time even if compilation were bypassed.
    with pytest.raises(MappingError) as protected:
        apply_output_mapping(state, {"v": 1}, [{"from": "/v", "to": "/secret/x"}])
    assert protected.value.code == "WORKFLOW_PATH_PROTECTED"
