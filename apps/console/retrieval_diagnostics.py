"""Fixed retrieval settings for operator index diagnostics.

Query-time retrieval belongs to the scenario's ``retrieve`` node, which carries its own
``retrieval_profile_ref``. The two document-set surfaces that still have to run a query -- the
one-off probe and the retrieval batch evaluation -- answer "is this index built and does it
find anything", not "how should this scenario search". They are index diagnostics, so they run
with settings the server owns and states on screen rather than asking an operator to pick a
profile that no scenario will use.

Those settings are not defined here. They are the authoring form's own defaults, so a change to
the form cannot leave the diagnostic behind.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.console.profile_fields import profile_defaults
from apps.tenancy.models import Organization

#: System-owned logical identity, one per tenant. Reserved: an authored profile never uses it,
#: because console authoring derives its logical id from the operator's display name.
DIAGNOSTIC_LOGICAL_ID = "sys_diag_retrieval"
DIAGNOSTIC_LOGICAL_DESCRIPTION = (
    "Sistem sahipli tanı araması. Operatör indeks sondaları ve retrieval değerlendirmeleri "
    "bu sabit ayarla çalışır; senaryolar kendi arama profillerini kullanır."
)


def diagnostic_retrieval_body() -> dict[str, Any]:
    """Return the fixed diagnostic settings: the retrieval form's own starting values."""

    return profile_defaults(ArtifactType.RETRIEVAL_PROFILE)


def diagnostic_retrieval_profile(*, organization: Organization, actor: str) -> ArtifactVersion:
    """Resolve the tenant's immutable diagnostic profile, publishing one only when needed.

    A persisted evaluation must point at a checksummed body. If the form defaults ever change,
    re-running a report has to be visibly a *different* measurement -- a new version with a new
    checksum -- instead of the same row quietly meaning something else. Nothing is published
    while rendering a page; this runs when a run is started.
    """

    body = diagnostic_retrieval_body()
    checksum = compute_checksum(body)
    with transaction.atomic():
        existing = (
            ArtifactVersion.objects.filter(
                organization=organization,
                type=ArtifactType.RETRIEVAL_PROFILE,
                logical_id=DIAGNOSTIC_LOGICAL_ID,
                checksum=checksum,
            )
            .order_by("-version")
            .first()
        )
        if existing is not None:
            return existing
        return create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.RETRIEVAL_PROFILE,
            logical_id=DIAGNOSTIC_LOGICAL_ID,
            body=body,
            created_by=actor,
            logical_description=DIAGNOSTIC_LOGICAL_DESCRIPTION,
            version_description="Sabit tanı ayarı.",
        )
