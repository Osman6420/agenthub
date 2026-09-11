"""Compile (and optionally promote) a scenario release from a spec YAML file.

Spec format::

    runtime_version: agenthub-runtime:3.0.0
    artifacts:
      - role: input_contract
        kind: InputContract
        logical_id: customer_query
        version: 1
      - role: output_contract
        kind: OutputContract
        logical_id: customer_answer
        version: 1
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.core.management.base import BaseCommand, CommandError

from apps.artifacts.gitops import TYPE_BY_KIND
from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.releases.authz import ReleaseAuthorizationError, resolve_release_manager
from apps.releases.compiler import ArtifactRef, CompileError, compile_release
from apps.releases.lifecycle import LifecycleError, promote


class Command(BaseCommand):
    help = "Compile a candidate ScenarioRelease from a spec file."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--scenario", required=True, help="org-slug/project-slug/scenario-slug")
        parser.add_argument("--spec", required=True, help="Path to the release spec YAML.")
        parser.add_argument("--actor", default="cli")
        parser.add_argument(
            "--promote", action="store_true", help="Promote the candidate to active."
        )

    def _resolve_scenario(self, dotted: str) -> Scenario:
        try:
            org_slug, project_slug, scenario_slug = dotted.split("/")
        except ValueError as exc:
            raise CommandError("--scenario must be 'org-slug/project-slug/scenario-slug'") from exc
        scenario = (
            Scenario.objects.filter(
                project__organization__slug=org_slug,
                project__slug=project_slug,
                slug=scenario_slug,
            )
            .select_related("project", "project__organization")
            .first()
        )
        if scenario is None:
            raise CommandError(f"scenario not found: {dotted}")
        return scenario

    def handle(self, *args: Any, **options: Any) -> None:
        scenario = self._resolve_scenario(options["scenario"])
        spec_path = Path(options["spec"])
        if not spec_path.is_file():
            raise CommandError(f"spec file not found: {spec_path}")
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}

        runtime_version = spec.get("runtime_version")
        if not runtime_version:
            raise CommandError("spec.runtime_version is required")

        refs: list[ArtifactRef] = []
        for entry in spec.get("artifacts", []):
            kind = entry.get("kind")
            if kind not in TYPE_BY_KIND:
                raise CommandError(f"unsupported kind in spec: {kind!r}")
            refs.append(
                ArtifactRef(
                    role=entry["role"],
                    type=TYPE_BY_KIND[kind],
                    logical_id=entry["logical_id"],
                    version=int(entry["version"]),
                )
            )

        try:
            release = compile_release(
                scenario=scenario,
                refs=refs,
                runtime_version=runtime_version,
                created_by=options["actor"],
            )
        except CompileError as exc:
            raise CommandError(f"compile failed: {exc}") from exc

        record_event(
            actor_type="user",
            actor_id=options["actor"],
            action="release.compile",
            outcome="success",
            organization_id=scenario.project.organization_id,
            resource_type="scenario_release",
            resource_id=str(release.pk),
            reason=release.artifact_manifest_sha256,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"compiled candidate release id={release.pk} "
                f"sha256={release.artifact_manifest_sha256}"
            )
        )

        if options["promote"]:
            # Fail-closed: promotion now goes through the gated lifecycle, which
            # requires an authorized release manager, a passing eval, and ready indexes.
            try:
                resolve_release_manager(
                    username=options["actor"],
                    organization_id=scenario.project.organization_id,
                    scenario=scenario,
                )
            except ReleaseAuthorizationError as exc:
                raise CommandError(f"not authorized to promote: {exc.code}") from exc
            try:
                promote(release=release, actor=options["actor"])
            except LifecycleError as exc:
                raise CommandError(
                    f"promotion denied: {exc.code}. Run `run_eval --release {release.pk}` "
                    f"first, then `promote_release --release {release.pk}`."
                ) from exc
            self.stdout.write(self.style.SUCCESS(f"promoted release id={release.pk} to active"))
