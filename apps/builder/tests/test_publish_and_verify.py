"""The single Studio action that replaces the publish → pin → compile → evaluate journey."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.builder.tests.conftest import BuilderFixture
from apps.console.scenario_defaults import prepare_scenario_contract_defaults
from apps.evaluations.models import EvalRun, EvalStatus
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.releases.scenario_artifacts import SCENARIO_SCOPED_ROLES

pytestmark = pytest.mark.django_db


def _url(bf: BuilderFixture) -> str:
    return reverse("builder_api:draft_publish_and_verify", args=[bf.draft.pk])


def _post(client: Client, bf: BuilderFixture) -> tuple[int, dict]:
    response = client.post(
        _url(bf),
        data=json.dumps({"revision": bf.draft.revision, "version_description": "ilk sürüm"}),
        content_type="application/json",
    )
    return response.status_code, json.loads(response.content)


def test_one_call_publishes_compiles_and_evaluates(client: Client, bf: BuilderFixture) -> None:
    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.author)

    status, body = _post(client, bf)

    assert status == 201
    assert body["ok"] is True
    assert body["published"]["version"] == 1
    # One operator action produced an immutable artifact, a candidate and an eval report.
    assert ArtifactVersion.objects.filter(
        organization=bf.org, type=ArtifactType.WORKFLOW_DEFINITION
    ).exists()
    release = ScenarioRelease.objects.get(pk=body["release"]["id"])
    assert release.status == ReleaseStatus.CANDIDATE
    assert EvalRun.objects.filter(release=release).exists()
    assert body["evaluation"]["level"] in {"success", "warning", "error"}


def test_default_eval_suite_removes_the_second_candidate_round_trip(
    client: Client, bf: BuilderFixture
) -> None:
    """Without a prepared suite the first candidate could never be evaluated."""

    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.author)

    _status, body = _post(client, bf)

    run = EvalRun.objects.get(release_id=body["release"]["id"])
    assert run.status != EvalStatus.ERROR or run.error_code != "EVAL_SUITE_NOT_PINNED"
    assert run.total_cases == 1
    assert ScenarioRelease.objects.filter(scenario=bf.scenario).count() == 1


def test_missing_artifacts_are_reported_without_creating_a_candidate(
    client: Client, bf: BuilderFixture
) -> None:
    """The draft still publishes; only candidate creation is withheld, with a reason."""

    client.force_login(bf.author)

    status, body = _post(client, bf)

    assert status == 200
    assert body["ok"] is False
    assert body["published"]["version"] == 1
    assert {entry["role"] for entry in body["missing"]} == {
        ArtifactType.INPUT_CONTRACT,
        ArtifactType.OUTPUT_CONTRACT,
        ArtifactType.EVAL_SUITE,
    }
    assert ScenarioRelease.objects.count() == 0


def test_a_viewer_cannot_publish_and_verify(client: Client, bf: BuilderFixture) -> None:
    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.viewer)

    response = client.post(
        _url(bf),
        data=json.dumps({"revision": bf.draft.revision, "version_description": "x"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert ScenarioRelease.objects.count() == 0
    assert ArtifactVersion.objects.count() == 3  # only the prepared scenario defaults


def test_another_tenant_cannot_reach_the_draft(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.outsider)

    response = client.post(
        _url(bf),
        data=json.dumps({"revision": bf.draft.revision, "version_description": "x"}),
        content_type="application/json",
    )

    assert response.status_code == 404
    assert ScenarioRelease.objects.count() == 0


def test_it_never_promotes_or_changes_live_traffic(client: Client, bf: BuilderFixture) -> None:
    """Candidate preparation only: an editor must not be able to reach live traffic."""

    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.author)

    _status, body = _post(client, bf)

    release = ScenarioRelease.objects.get(pk=body["release"]["id"])
    assert release.status == ReleaseStatus.CANDIDATE
    assert not ScenarioRelease.objects.filter(status=ReleaseStatus.ACTIVE).exists()
    assert "promote" not in json.dumps(body)


def test_a_stale_revision_is_rejected(client: Client, bf: BuilderFixture) -> None:
    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.author)

    response = client.post(
        _url(bf),
        data=json.dumps({"revision": bf.draft.revision + 5, "version_description": "x"}),
        content_type="application/json",
    )

    assert response.status_code == 409
    assert ScenarioRelease.objects.count() == 0


def test_derived_manifest_reports_pins_without_asking_for_selection(
    client: Client, bf: BuilderFixture
) -> None:
    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.author)
    _post(client, bf)

    response = client.get(
        reverse("builder_api:release_manifest_derived", args=[bf.scenario.public_id])
    )
    body = json.loads(response.content)

    assert response.status_code == 200
    assert body["available"] is True and body["ok"] is True
    roles = {pin["role"] for pin in body["pins"]}
    assert "workflow_definition" in roles
    assert set(SCENARIO_SCOPED_ROLES) <= roles
    assert body["missing"] == []


def test_node_artifact_library_serves_history_and_copy_sources(
    client: Client, bf: BuilderFixture
) -> None:
    """Version history and copying replace picking raw logical ids in the manifest panel."""

    prepare_scenario_contract_defaults(scenario=bf.scenario, actor="author")
    client.force_login(bf.author)

    response = client.get(
        reverse("builder_api:node_artifact_library", args=[bf.draft.pk]),
        {"node_id": "format", "kind": "prompt"},
    )
    body = json.loads(response.content)

    assert response.status_code == 200
    # The role is server-derived; the caller never names it.
    assert body["role"].startswith("gen_")
    assert body["versions"] == []
    assert isinstance(body["library"], list)


def test_node_artifact_library_denies_a_viewer(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.viewer)

    response = client.get(
        reverse("builder_api:node_artifact_library", args=[bf.draft.pk]),
        {"node_id": "format", "kind": "prompt"},
    )

    assert response.status_code == 403
