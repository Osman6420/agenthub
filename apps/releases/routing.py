"""Consumer-scoped canary-aware release selection (Sprint 6).

The gateway calls :func:`select_release` only *after* it has authenticated the
consumer and authorized its scenario binding. If that consumer has a live, unexpired
canary assignment for the scenario, it is routed to the pinned canary release;
otherwise it gets the scenario's single active release. Selection is server-side and
never reads a release id from the client, so an arbitrary candidate can never be
invoked.
"""

from __future__ import annotations

from django.utils import timezone

from apps.catalog.models import Scenario
from apps.identity.models import Consumer
from apps.releases.models import CanaryStatus, ReleaseCanary, ReleaseStatus, ScenarioRelease
from apps.releases.services import get_active_release


def select_release(
    *, scenario: Scenario, consumer: Consumer
) -> tuple[ScenarioRelease | None, bool]:
    """Return ``(release, is_canary)`` for this consumer, or ``(None, False)``."""
    canary = (
        ReleaseCanary.objects.filter(
            scenario=scenario,
            consumer=consumer,
            status=CanaryStatus.ACTIVE,
            expires_at__gt=timezone.now(),
        )
        .select_related("release")
        .first()
    )
    if canary is not None and canary.release.status == ReleaseStatus.CANARY:
        return canary.release, True
    return get_active_release(scenario), False
