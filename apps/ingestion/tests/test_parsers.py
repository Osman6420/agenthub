"""Unit tests for the governed document parsers (Phase 2 · P7.1).

Pure-stdlib, deterministic, no DB and no egress. Covers happy path, invalid/oversize input,
deny-by-default MIME, HTML script/style stripping, and the content-free failure contract.
"""

from __future__ import annotations

import pytest

from apps.ingestion.parsers import (
    MAX_PARSED_CHARS,
    ParsedContent,
    ParserError,
    get_parser,
    parse_document,
)


def test_plain_text_parses_and_strips() -> None:
    out = parse_document("text/plain", b"  hello world  ")
    assert isinstance(out, ParsedContent)
    assert out.text == "hello world"
    assert out.parser == "text"


def test_markdown_passthrough() -> None:
    out = parse_document("text/markdown", b"# Title\n\nBody text")
    assert out.text == "# Title\n\nBody text"
    assert out.parser == "markdown"


def test_csv_becomes_pipe_joined_rows() -> None:
    out = parse_document("text/csv", b"name,city\nAyse,Istanbul\nMehmet,Ankara\n")
    assert out.text == "name | city\nAyse | Istanbul\nMehmet | Ankara"
    assert out.parser == "csv"
    assert out.element_count == 3


def test_csv_skips_blank_rows() -> None:
    out = parse_document("text/csv", b"a,b\n\n,\nx,y\n")
    assert out.text == "a | b\nx | y"


def test_json_is_flattened_deterministically() -> None:
    out = parse_document(
        "application/json",
        b'{"policy": {"returns": "30 days"}, "tags": ["a", "b"]}',
    )
    assert out.text == "policy.returns: 30 days\ntags[0]: a\ntags[1]: b"
    assert out.parser == "json"


def test_json_invalid_fails_closed() -> None:
    with pytest.raises(ParserError) as exc:
        parse_document("application/json", b"{not json")
    assert exc.value.code == "JSON_INVALID"


def test_html_extracts_visible_text_and_drops_script_style() -> None:
    html = (
        b"<html><head><title>T</title><style>.x{color:red}</style></head>"
        b"<body><h1>Heading</h1><p>Para one.</p>"
        b"<script>alert('x')</script><p>Para two.</p></body></html>"
    )
    out = parse_document("text/html", html)
    assert "Heading" in out.text
    assert "Para one." in out.text
    assert "Para two." in out.text
    # Script/style bodies never leak into extracted text.
    assert "alert" not in out.text
    assert "color:red" not in out.text
    assert out.parser == "html"


def test_unsupported_mime_denies_by_default() -> None:
    # image/* (OCR is the deferred P7.3), octet-stream, and empty MIME have no registered parser.
    for mime in ("image/png", "image/jpeg", "application/octet-stream", ""):
        with pytest.raises(ParserError) as exc:
            parse_document(mime, b"data")
        assert exc.value.code == "PARSER_UNSUPPORTED"


def test_empty_document_fails_closed() -> None:
    with pytest.raises(ParserError) as exc:
        parse_document("text/plain", b"   \n\t  ")
    assert exc.value.code == "EMPTY_DOCUMENT"


def test_non_utf8_fails_closed_without_content() -> None:
    with pytest.raises(ParserError) as exc:
        parse_document("text/plain", b"\xff\xfe\x00bad")
    assert exc.value.code == "DOCUMENT_NOT_UTF8"
    # The error message is the stable code only — never document bytes.
    assert str(exc.value) == "DOCUMENT_NOT_UTF8"


def test_oversize_output_is_bounded() -> None:
    big = b"a" * (MAX_PARSED_CHARS + 1)
    with pytest.raises(ParserError) as exc:
        parse_document("text/plain", big)
    assert exc.value.code == "PARSED_TOO_LARGE"


def test_get_parser_returns_registered_parser() -> None:
    assert get_parser("text/plain").name == "text"
    assert get_parser("text/html").name == "html"
