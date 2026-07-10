# Task Plan: sprint-6-eval-promotion-rollback

## Task summary

Bind release activation to deterministic evaluation gates, add consumer-scoped
canaries, and provide audited atomic promotion and rollback.

## Background

Sprint 2 added compilation and an intentionally minimal ungated active-pointer swap.
Sprint 4 added governed synchronous RAG runtime, and Sprint 5 added promotable staged
indexes. Sprint 6 replaces the temporary promotion path with a fail-closed lifecycle.

Model groundwork already exists: `ReleaseStatus` defines `candidate/canary/active/
superseded/rolled_back`, `ArtifactType.EVAL_SUITE` is defined, the `release_manager`
role exists, and `ScenarioRelease` enforces a DB single-active constraint. Sprint 6
adds the evaluation records/engine, gated lifecycle services, index-version pins, and
canary routing on top of this groundwork. To preserve unrelated runtime/gateway test
setup, the existing atomic swap (`compiler.promote_release`) is retained as a clearly
marked internal primitive; the fail-closed gate is a new operator-facing lifecycle
service that the console and management commands call.

## Scope

- `evaluations` models for eval runs/case results and an EvalSuite loader.
- Deterministic RAG assertions and isolated candidate invocation.
- Optional index-version pins in release manifests and index-readiness smoke gate
  (also closes the current gap where `ReleaseBundle.index_versions` is always empty, so
  the Sprint 5 pgvector retriever becomes reachable end-to-end through the gateway).
- Atomic candidate/canary/active/superseded/rolled-back transitions.
- Consumer-scoped, time-bounded canary routing after normal binding authorization.
- Release-manager/platform-admin authorization for console lifecycle actions.
- Audited management commands and custom operator-console release actions.
- Cache-safe promotion and rollback tests against gateway routing.

## Non-goals

- LLM-as-judge as a sole promotion authority, percentage canaries, automated rollback,
  arbitrary eval Python, workflow/agent trajectory assertions, or production metrics.
- Django Admin as a management surface; ADR-0001 requires the custom console.

## Acceptance criteria

- A failed or missing required eval blocks promotion.
- Candidate eval cannot change the active pointer or bypass tenant/release pins.
- A canary consumer routes to its eligible candidate; other consumers stay active.
- Promotion atomically activates the candidate and supersedes the previous active.
- Rollback atomically restores a known-good superseded release without rebuilding.
- Every allow/deny lifecycle decision is tenant-scoped and audited without payloads.

## Affected components

New `evaluations` app; `releases`, `orchestration`, `gateway`, `console`, `tenancy`,
artifact validation, settings, migrations, commands, tests, and documentation.

## Interfaces affected

- Existing `promote_release` becomes fail-closed and requires passing evaluation.
- Gateway release selection gains an authorized consumer-canary branch.
- New internal/management interfaces: run eval, start/stop canary, promote, rollback.
- New authenticated custom-console release lifecycle actions; no new public endpoint.

## Data impact

Additive EvalRun/EvalCaseResult/ReleaseCanary records. Reports store assertion ids,
outcomes, safe reason codes, and usage counts only—never raw prompts/model output.

## Security impact

Eval definitions are data, not executable code. Assertions use an allowlist and
bounded cases/input sizes. Candidate invocation uses exact release/tenant/index pins
and cannot be reached from the public gateway without a valid canary assignment.

## Authorization impact

Lifecycle mutations require `release_manager` in the release organization or a
platform admin. Gateway still authenticates the consumer and authorizes its scenario
binding before considering a time-bounded canary for that same consumer/scenario.

## Observability impact

Audit eval completion, promotion/canary/rollback allows and denials with actor,
organization, release, stable reason, and outcome. No raw eval inputs/outputs in logs.

## Migration impact

Additive evaluation and canary tables/constraints. No destructive migration. Existing
release rows remain readable; new promotion attempts require eval evidence.

## Dependencies

No new production dependency is expected. Uses Django, jsonschema, and existing
runtime/provider seams.

## Implementation steps

1. Add task records, EvalSuite schema validation, models, and additive migrations.
2. Add candidate runtime seam and bounded deterministic assertion engine.
3. Add eval runner/report persistence and index readiness checks.
4. Replace minimal promotion with gated lifecycle services and rollback.
5. Add canary assignments and gateway resolution after binding authorization.
6. Add release-manager auth helpers, console actions, and management commands.
7. Add unit/integration/security/migration/gateway tests and update current-state docs.

## Test plan

- Eval loader rejects unknown assertions, malformed cases, excessive cases/input.
- Passing/failing/error runs persist redacted reports and do not alter active release.
- Missing/failed eval blocks promotion and records denial audit.
- Cross-tenant release/eval/canary/rollback attempts fail server-side.
- Canary only affects assigned active consumer in its time window.
- Promote/rollback route subsequent gateway requests to the expected release.
- Concurrent promotion preserves the single-active invariant.
- Migration forward/rollback smoke on SQLite and PostgreSQL.

## Rollout plan

Apply additive migrations, deploy read-compatible code, run evals for candidates, then
enable lifecycle commands/console actions. Existing active releases remain active.

## Rollback plan

Disable lifecycle actions and canary resolution; retain new records. Restore the
previous application version only while migrations remain additive/read-compatible.
Schema removal requires separately approved destructive work.

## Risks

- Tightening `promote_release` can break scripts relying on `--promote`; provide clear
  errors and separate run-eval/promote commands.
- Canary routing is authorization-sensitive and may expose an unevaluated candidate if
  binding/release/tenant/time checks are incomplete.
- Deterministic stubs prove governance, not real-model quality.

## Open questions

- Production safety suite ownership and approval thresholds.
- Canary monitoring/automatic abort thresholds arrive with Sprint 7 metrics.

## Status

In progress. Verified on SQLite and PostgreSQL:

- Implemented + verified: `eval_suite` artifact schema (bounded, allowlisted
  deterministic assertions); `apps/evaluations` (EvalRun/EvalCaseResult, assertion
  engine, isolated candidate runner with redacted audited reports); fail-closed
  `apps/releases/lifecycle.promote` (passing-eval + tenant-owned ready-index gates)
  and atomic `rollback`; optional manifest `index_versions` pins now resolved into the
  runtime bundle (closes the earlier end-to-end retrieval gap); `can_manage_releases`
  (`release_manager`/platform-admin) authorization helper.
- Pending (next increment, needs public-routing approval for canary): consumer-scoped
  canary routing in the gateway; operator-console lifecycle actions; and
  `run_eval`/`promote_release`(gated)/`rollback` management commands.

## Completion criteria

All Definition of Done gates pass on SQLite and PostgreSQL; authorization denial,
gateway routing, audit, migration, promotion, and rollback evidence is recorded.
