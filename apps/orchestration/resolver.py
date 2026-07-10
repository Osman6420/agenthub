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

from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role

_CACHE_TTL = 300


@dataclass(frozen=True)
class ReleaseBundle:
    release_id: int
    organization_id: int
    prompt_text: str
    policy: dict[str, Any]
    model_profile: dict[str, Any]
    retrieval_profile: dict[str, Any]
    input_contract: dict[str, Any] | None
    output_contract: dict[str, Any] | None
    index_versions: list[int] = field(default_factory=list)


def _build(release: ScenarioRelease) -> ReleaseBundle:
    prompt_body = get_artifact_body_for_role(release, "prompt") or {}
    manifest = release.manifest if isinstance(release.manifest, dict) else {}
    raw_pins = manifest.get("index_versions", [])
    index_versions = [int(v) for v in raw_pins if isinstance(v, int) and not isinstance(v, bool)]
    return ReleaseBundle(
        release_id=release.id,
        organization_id=release.scenario.project.organization_id,
        prompt_text=str(prompt_body.get("template", "")),
        policy=get_artifact_body_for_role(release, "policy") or {},
        model_profile=get_artifact_body_for_role(release, "model_profile") or {},
        retrieval_profile=get_artifact_body_for_role(release, "retrieval_profile") or {},
        input_contract=get_artifact_body_for_role(release, "input_contract"),
        output_contract=get_artifact_body_for_role(release, "output_contract"),
        index_versions=index_versions,
    )


def resolve_bundle(release: ScenarioRelease) -> ReleaseBundle:
    key = f"relbundle:{release.id}:{release.artifact_manifest_sha256}"
    bundle = cache.get(key)
    if bundle is None:
        bundle = _build(release)
        cache.set(key, bundle, _CACHE_TTL)
    return bundle
