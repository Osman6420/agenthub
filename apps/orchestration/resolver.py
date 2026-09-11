"""Release-bundle resolver.

Loads the pinned artifact bodies a release needs to run. Cached by the immutable
release id: a release's artifacts never change, so the cached bundle can never go
stale. The active-release *pointer* is resolved fresh per request (not cached), so
promotion/rollback take effect immediately without cache invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.core.cache import cache

from apps.artifacts.governed_dsl import normalize_retrieval_profile
from apps.releases.execution import release_revision
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role

_CACHE_TTL = 300


@dataclass(frozen=True)
class ReleaseBundle:
    release_id: int
    organization_id: int
    scenario_id: int
    prompt_text: str
    policy: dict[str, Any]
    model_profile: dict[str, Any]
    retrieval_profile: dict[str, Any]
    input_contract: dict[str, Any] | None
    output_contract: dict[str, Any] | None
    index_versions: list[int] = field(default_factory=list)
    document_set_version_ids: list[int] = field(default_factory=list)
    data_selection: str = "legacy_pinned"
    document_set_ids: list[int] = field(default_factory=list)


def _build(release: ScenarioRelease, snapshot: dict[str, Any] | None = None) -> ReleaseBundle:
    def body_for(role: str) -> dict[str, Any] | None:
        if snapshot is None:
            return get_artifact_body_for_role(release, role)
        artifact = snapshot["artifacts"].get(role)
        return artifact["body"] if artifact is not None else None

    prompt_body = body_for("prompt") or {}
    manifest = snapshot["manifest"] if snapshot is not None else release.manifest
    raw_pins = manifest.get("index_versions", [])
    index_versions = [int(v) for v in raw_pins if isinstance(v, int) and not isinstance(v, bool)]
    raw_dsv = manifest.get("document_set_versions", [])
    document_set_version_ids = [
        int(v) for v in raw_dsv if isinstance(v, int) and not isinstance(v, bool)
    ]
    raw_retrieval_profile = body_for("retrieval_profile")
    return ReleaseBundle(
        release_id=release.id,
        organization_id=release.scenario.project.organization_id,
        scenario_id=release.scenario_id,
        prompt_text=str(prompt_body.get("template", "")),
        policy=body_for("policy") or {},
        model_profile=body_for("model_profile") or {},
        retrieval_profile=(
            normalize_retrieval_profile(raw_retrieval_profile) if raw_retrieval_profile else {}
        ),
        input_contract=body_for("input_contract"),
        output_contract=body_for("output_contract"),
        index_versions=index_versions,
        document_set_version_ids=document_set_version_ids,
        data_selection=(snapshot["data"]["selection"] if snapshot is not None else "legacy_pinned"),
        document_set_ids=(snapshot["data"]["document_set_ids"] if snapshot is not None else []),
    )


def resolve_bundle(release: ScenarioRelease) -> ReleaseBundle:
    # Even a cached resolved bundle must not hide a missing/invalid required revision.
    _, snapshot = release_revision(release)
    key = (
        f"relbundle:{release.organization_id}:{release.scenario_id}:"
        f"{release.execution_contract}:{release.id}:{release.artifact_manifest_sha256}"
    )
    bundle = cache.get(key)
    if bundle is None:
        bundle = _build(release, snapshot)
        cache.set(key, bundle, _CACHE_TTL)
    return bundle
