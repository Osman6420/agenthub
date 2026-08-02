from __future__ import annotations

import logging

from apps.observability.logging import StripExpectedClientErrorTraceback


def _record(*, name: str, status_code: int) -> logging.LogRecord:
    try:
        raise PermissionError("safe-test-error")
    except PermissionError:
        record = logging.LogRecord(name, logging.WARNING, __file__, 1, "denied", (), None)
        record.exc_info = __import__("sys").exc_info()
    record.status_code = status_code
    return record


def test_expected_django_client_error_keeps_record_without_traceback() -> None:
    record = _record(name="django.request", status_code=403)

    assert StripExpectedClientErrorTraceback().filter(record) is True
    assert record.exc_info is None


def test_unexpected_server_and_non_django_errors_keep_traceback() -> None:
    server_error = _record(name="django.request", status_code=500)
    application_error = _record(name="apps.gateway", status_code=403)

    assert StripExpectedClientErrorTraceback().filter(server_error) is True
    assert server_error.exc_info is not None
    assert StripExpectedClientErrorTraceback().filter(application_error) is True
    assert application_error.exc_info is not None
