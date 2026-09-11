"""Immutable publication targets for a reviewed source revision, never an authority grant."""

from typing import Any

from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.rest_setup_schedule import validate_setup_schedule


def validate_revision_schedule(schedule: Any) -> None:
    if isinstance(schedule, dict) and "publication_targets" in schedule:
        targets = schedule["publication_targets"]
        if (
            "preparation" not in schedule
            or not isinstance(targets, list)
            or not 1 <= len(targets) <= 200
            or any(type(pk) is not int or not 0 < pk <= 9223372036854775807 for pk in targets)
            or len(set(targets)) != len(targets)
        ):
            raise RestServiceError("SOURCE_REVISION_PUBLICATION_INVALID")
        schedule = {key: value for key, value in schedule.items() if key != "publication_targets"}
    validate_setup_schedule(schedule)
