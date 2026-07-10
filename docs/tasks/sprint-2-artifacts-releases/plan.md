# Task Plan: sprint-2-artifacts-releases

## Task summary

Implement Sprint 2 of the [v3 target plan](../../../agenthub-v3-django-plan.md#25-uygulama-asamalari):
the immutable artifact registry, the compiled `ScenarioRelease` with an
active-release invariant, the release compiler, and GitOps import/export +
supporting management commands.

## Background

Sprint 1 delivered tenant/identity/catalog. Runtime behavior must be pinned by an
immutable release composed of versioned artifacts (prompt, policy, contract, model
profile, ...). This sprint builds that registry and the compiler that assembles a
reproducible release, so later runtime sprints only ever read pinned versions.

## Scope

- `artifacts`: `ArtifactVersion` (immutable, versioned, checksummed, tenant-scoped)
  with per-type validation and inline-secret rejection.
- `releases`: `ScenarioRelease` with a manifest of pinned versions/checksums and a
  DB-enforced single-active-release-per-scenario invariant; `compile_release` and a
  minimal transactional `promote_release`.
- Management commands: `validate_artifacts`, `compile_release`, `import_gitops`,
  `export_gitops`.
- Console: read-only Artifacts and Releases screens (tenant-scoped).

## Non-goals

- Full promotion/canary/rollback lifecycle and evaluation gates (Sprint 6).
- Runtime that executes a release (gateway/RAG, Sprint 3–4).
- Deep semantic validation of every artifact type (prompt/model specifics arrive
  with their runtime sprints); Sprint 2 validates JSON Schema contracts, structural
  shape, and secret-safety.

## Acceptance criteria

From the v3 plan (Sprint 2):

- A missing reference, a schema mismatch, or an inline secret makes `compile_release`
  fail (no candidate is created).
- An `ArtifactVersion` cannot be modified after creation.
- The single-active-release-per-scenario constraint holds at the transaction/DB
  level (a second active release is rejected).

## Affected components

New apps `artifacts`, `releases`. Console gains two read screens. New dependency
`PyYAML` for GitOps import/export.

## Interfaces affected

New management commands (operational). New console read screens. No public product
API yet.

## Data impact

New tables: `artifacts_artifactversion`, `releases_scenariorelease`. Immutable rows;
manifests stored as JSON with checksums. No PII.

## Security impact

- Inline secrets are rejected on artifact create/import (only `secret:<name>`
  references allowed); scanning covers YAML/JSON bodies.
- Artifact bodies are immutable and checksummed; a release pins exact versions and a
  manifest SHA-256 so runtime behavior is reproducible and tamper-evident.
- GitOps import validates schema and secret-safety before persisting; export never
  emits secret values.
- Tenant scope is enforced: a release may only reference artifacts in its scenario's
  organization.

## Authorization impact

Compilation/promotion are operator actions; role gating (release_manager) is applied
in the console/commands. Capability enforcement on the request path is still Sprint 3.

## Observability impact

Compile, import, and promote emit audit events (actor, action, resource, outcome,
reason).

## Migration impact

Additive initial migrations for the two apps, including a partial unique index for
the active-release constraint. Verified with `makemigrations --check` and applied to
real PostgreSQL.

## Dependencies

New production dependency: `PyYAML` (GitOps import/export). ADR-approved as part of
implementing the plan.

## Implementation steps

1. `artifacts` model + type validators + inline-secret scanner + immutability + tests.
2. `releases` model + active-release partial-unique constraint.
3. `compile_release` (resolve refs, validate, checksum, create candidate) and a
   minimal transactional `promote_release`.
4. Management commands: `validate_artifacts`, `compile_release`, `import_gitops`,
   `export_gitops`.
5. Console Artifacts + Releases read screens.
6. Migrations; tests for all acceptance criteria; run gates on SQLite + Postgres.

## Test plan

- Compile fails on missing reference, on invalid JSON-Schema contract, and on an
  inline secret; succeeds and produces a stable manifest checksum on valid input.
- `ArtifactVersion` update after creation raises; checksum matches canonical body.
- Two active releases for one scenario → IntegrityError (constraint holds).
- GitOps import rejects a body containing an inline secret; export round-trips.

## Rollout plan

Additive; behind CI gates. Compilation produces candidates only; nothing goes active
without the (later) promotion path.

## Rollback plan

Revert the commit; drop the two new tables (greenfield, no production data).

## Risks

- Inline-secret detection is heuristic; mitigated by a conservative denylist + tests
  and by keeping `secret:<name>` the only accepted form.
- Partial unique index behavior differs across backends; verified on both SQLite and
  PostgreSQL.

## Open questions

- Canonical serialization for checksums (key ordering, separators) — fixed here to
  sorted-key compact JSON; revisit if cross-language producers are added.

## Status

Verified — all gates green; 37 tests pass on SQLite and real PostgreSQL; the full
operator flow (GitOps import → validate → compile → promote) was exercised against
the dev database and surfaced in the console on 2026-07-10. Evidence in
[`verification.md`](verification.md). Not yet `Completed`: gated promotion/canary/
rollback + eval (Sprint 6) and human review remain.

## Completion criteria

Map to the [Definition of Done](../../ai/definition-of-done.md): acceptance criteria
met with recorded evidence; immutability and constraint enforced and tested; secret
safety verified; gates green on SQLite and PostgreSQL; docs and master plan updated.
