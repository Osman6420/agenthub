"""Safe logging filters that preserve events while removing expected client-error stacks."""

from __future__ import annotations

import logging


class StripExpectedClientErrorTraceback(logging.Filter):
    """Keep Django's 4xx record but omit its redundant exception traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        status_code = getattr(record, "status_code", None)
        if record.name.startswith("django.request") and isinstance(status_code, int):
            if 400 <= status_code < 500:
                record.exc_info = None
                record.exc_text = None
                record.stack_info = None
        return True
