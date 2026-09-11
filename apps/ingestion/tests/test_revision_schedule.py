"""Revision publication schema rejects malformed intent without granting authority."""

from importlib import import_module

import pytest
from django.apps import apps
from django.db import DatabaseError, connection, transaction

from apps.ingestion.connector_jobs import source_checksum
from apps.ingestion.models import SourceConfigurationRevision
from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.revision_schedule import validate_revision_schedule
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest


@pytest.mark.django_db
def test_revision_publication_schema_and_immutable_history(governed_rest):
    source = governed_rest[-1]
    base = {"interval_seconds": 3600, "preparation": "a" * 64}
    invalid = [None, {}, [], [True], [0], [-1], [1, 1], [2**63], ["1"], [1.5], list(range(1, 202))]
    for targets in invalid:
        config = base | {"publication_targets": targets}
        with pytest.raises(RestServiceError):
            validate_revision_schedule(config)
        if connection.vendor == "postgresql":
            with pytest.raises(DatabaseError, match="PUBLICATION_INVALID"), transaction.atomic():
                SourceConfigurationRevision.objects.create(
                    source=source,
                    root_source=source,
                    organization=source.organization,
                    number=1,
                    checksum=source_checksum(source),
                    is_current=True,
                    schedule_config=config,
                    created_by="synthetic",
                )
    valid = base | {"publication_targets": [1, 9223372036854775807]}
    validate_revision_schedule(valid)
    revision = SourceConfigurationRevision.objects.create(
        source=source,
        root_source=source,
        organization=source.organization,
        number=1,
        checksum=source_checksum(source),
        is_current=True,
        schedule_config=valid,
        created_by="synthetic",
    )
    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError, match="IMMUTABLE"), transaction.atomic():
            SourceConfigurationRevision.objects.filter(pk=revision.pk).update(schedule_config=None)
        migration = import_module("apps.ingestion.migrations.0041_revision_publication_schedule")
        with pytest.raises(RuntimeError, match="EMPTY_HISTORY"):
            migration.reverse(apps, connection.schema_editor(atomic=False))


@pytest.mark.django_db
def test_edit_input_preserves_publication_only_for_existing_reviewed_targets(governed_rest):
    from apps.console.rest_setup_forms import InputStep
    from apps.documents.tests.test_phase_2_8_part_5 import _profiles
    from apps.ingestion.preparation import configure_preparation

    _, actor, _, docset, source = governed_rest
    embedding, chunking, retrieval = _profiles(source.organization)
    policy = configure_preparation(
        document_set=docset,
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor=str(actor.pk),
    )
    data = {
        "sync_mode": "periodic",
        "interval_seconds": "3600",
        "preparation_mode": "promote_if_safe",
        "input_dataset": "reviewed",
    }
    form = InputStep(
        data,
        definition=source.rest_contract.definition,
        preparation_policy=policy,
        publication_targets=[1],
    )
    assert form.is_valid(), form.errors
    assert form.schedule["publication_targets"] == [1]
    unavailable = InputStep(
        data, definition=source.rest_contract.definition, preparation_policy=policy
    )
    assert not unavailable.is_valid()
