"""Exercise manager actions through the real console and current release lifecycle."""

import pytest
from django.urls import reverse

from apps.console.tests.test_candidate_authority import _user
from apps.console.tests.test_candidate_authority import candidate as candidate
from apps.identity.models import ScenarioResponsibility
from apps.releases.models import ReleaseStatus

pytestmark = pytest.mark.django_db


def test_manager_can_evaluate_and_publish_but_viewer_cannot(client, candidate):
    scenario = candidate["scenario"]
    release = candidate["release"]
    manager = _user(candidate["org"], "combined-manager", scenario, ScenarioResponsibility.MANAGER)
    client.force_login(manager)
    assert client.get(reverse("console:scenario_detail", args=[scenario.pk])).status_code == 200
    assert client.post(reverse("console:release_run_eval", args=[release.pk])).status_code == 302
    assert client.post(reverse("console:release_promote", args=[release.pk])).status_code == 302
    release.refresh_from_db()
    assert release.status == ReleaseStatus.ACTIVE
    client.force_login(candidate["viewer"])
    assert client.post(reverse("console:release_promote", args=[release.pk])).status_code == 403


def test_manager_still_requires_successful_evaluation(client, candidate):
    scenario = candidate["scenario"]
    release = candidate["release"]
    manager = _user(candidate["org"], "unready-manager", scenario, ScenarioResponsibility.MANAGER)
    client.force_login(manager)
    response = client.post(reverse("console:release_promote", args=[release.pk]))
    assert response.status_code == 302
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE
