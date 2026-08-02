# Task Plan: Phase 2.9 Post-completion Audit

## Task summary

Independently verify whether Phase 2.9 closed every defect and UI gap recorded by the 2026-07-31
role/UI audit, using the committed current build, repository checks, deterministic browser gate, and
live in-app browser role journeys.

## Background

The owner reports Phase 2.9 implementation is finished. The committed component plan remains the
intent/status authority, while code, migrations, tests, runtime configuration, browser behavior,
and task verification records are the implementation authorities. Earlier observations made against
an uncommitted intermediate worktree are excluded from final evidence.

## Scope

- Reconcile the Phase 2.9 component status and Parts 1–7 verification records with current HEAD.
- Re-test the original high, medium, and UX findings with matched permitted/denied identities.
- Run applicable SQLite/PostgreSQL, frontend, type, lint/format, schema, and browser gates.
- Verify configured Gemini model/embedding profiles before dependent live-provider/index journeys.
- Inspect current-build UI for functional errors, browser console/network failures, click cost,
  comprehension, keyboard focus, and responsive behavior.
- Record remaining defects and distinguish fixed, partial, blocked, regressed, and unverified paths.

## Non-goals

- Implement fixes discovered by this audit.
- Reset the local database or delete retained audit fixtures.
- Access production systems or production data.
- Enable uncontrolled connector/OCR/tool egress.
- Store or reveal credentials, tokens, prompts, provider responses, or document content.

## Acceptance criteria

- Every original audit finding maps to current code/test and live-browser evidence.
- Exact-role allow/deny, same-tenant cross-scenario/set, and cross-tenant behavior is exercised.
- Scenario callability and served-index lifecycle work without direct database/bootstrap mutation.
- Model/embedding prerequisites are proven before dependent live journeys; missing prerequisites are
  reported as blocked rather than passed.
- Repository and deterministic browser gates have exact pass/fail counts and failure evidence.
- The final conclusion states whether Phase 2.9 may truthfully be marked completed.

## Affected components

Read-only assessment of console, identity, catalog/releases, documents/ingestion, gateway/runtime,
builder/AI authoring, frontend browser automation, Compose runtime, and planning/evidence records.

## Interfaces affected

None. Existing console and API interfaces are tested, not changed.

## Data impact

Only synthetic/disposable local test records may be created by the repository-owned browser fixture
or safe UI journeys. No reset, destructive purge, or non-synthetic mutation is authorized. Secrets
remain environment-only.

## Security and authorization impact

No policy change. The audit verifies exact-object authorization, tenant isolation, non-disclosing
denials, CSRF/mutation gating, provider governance, and sensitive-data redaction.

## Observability impact

Existing browser console/network results, HTTP statuses, logs, audit outcomes, and request IDs may
be inspected. No logging or telemetry configuration is changed.

## Migration impact

No migration is planned. Applied state and drift are checked read-only.

## Dependencies

Current committed HEAD, canonical Compose topology, healthy local services, repository virtual
environment/toolchain, in-app browser, synthetic Phase 2.9 fixtures, and approved Gemini environment
secret if a configured live profile requires it.

## Implementation steps

1. Re-read current HEAD, worktree, Phase 2.9 status, part evidence, and live topology.
2. Map original findings to changed symbols, tests, routes, and current acceptance evidence.
3. Run deterministic automated quality and browser gates.
4. Establish model/embedding prerequisites, then run dependent live browser/provider journeys.
5. Exercise exact-role allowed and forbidden console/API paths and UX breakpoints.
6. Record evidence and review the result as staff engineer, AppSec, SRE, and UX reviewer.

## Test plan

- Repository browser gate and focused Phase 2.9 backend/frontend tests.
- PostgreSQL non-owner/RLS and same-tenant exact-scope tests.
- Ruff lint/format, mypy, Django check, migration drift, frontend tests/type/build.
- Browser role journeys for runtime/release controls, scenario lifecycle, documents/index/retrieval,
  governed setup, Studio AI, content access, navigation, direct denial, and responsive/keyboard UX.
- Browser console/network error review and bounded service-log inspection.

## Rollout and rollback

Not applicable: audit only. Synthetic browser-gate databases are isolated and disposable; retained
live synthetic records are documented. No product rollback is performed.

## Risks

- A green deterministic browser fixture may not prove the current long-lived local database state.
- Live provider/profile rows without matching environment secrets are not usable evidence.
- Broad role matrices can miss same-tenant adjacent-object disclosure unless exact paired objects
  are used.
- The current local database may contain prior synthetic state that shortens or masks setup steps.
- Browser automation can prove interaction but not fully replace human comprehension judgment.

## Status

Completed 2026-08-02. The audit is complete; Phase 2.9 itself remains in progress because the
required configured live Gemini Studio smoke failed before candidate creation.

## Completion criteria

Evidence is recorded in `verification.md` and `report.md`; skipped or blocked checks are explicit,
and no Phase 2.9 completion claim exceeds the observed current state.
