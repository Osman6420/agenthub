# Comprehensive live application QA — 2026-09-04

## Task summary

Understand the running AgentHub application and execute an evidence-backed functional, RAG,
API, authorization, UI and UX assessment against the current working tree. Record the roadmap
before execution and the actual results in `verification.md`.

## Background

The application is already running locally. The active handoff identifies the mandatory browser
gate as the remaining verification blocker for the uncommitted scenario/document authoring work.
The repository also contains ten user-supplied Turkish PDF files under `Test Datası/` for a realistic
document ingestion and RAG journey.

## Scope

- Reconcile repository architecture, user journeys, current plans, live Compose state and the
  uncommitted worktree before relying on prior evidence.
- Run repository formatter, linter, type, Django, migration, Python, frontend and real-browser
  automated gates against the current tree.
- Exercise the running console in a real browser, including navigation, responsive behavior,
  keyboard/focus behavior, visible role affordances and actionable error feedback.
- Exercise representative project/scenario, document-set, RAG, release, consumer, run and
  observability journeys at their supported boundaries.
- Pair browser authorization checks with direct HTTP negative probes where practical.
- Use only synthetic/local records and a bounded selection of the supplied PDF corpus.
- Record actual results, evidence, blockers, findings, cleanup state and residual risks.

## Non-goals

- Fixing defects discovered by this assessment; fixes require a separately scoped implementation
  task and updated plan.
- Resetting the canonical local database, purging retained content, deleting existing resources or
  exercising irreversible operations.
- Calling real model, embedding, OCR, Confluence, REST connector or tool endpoints without an
  already approved and configured local profile.
- Claiming production/OpenShift, live LDAP, scale, load or external-provider acceptance from this
  local environment.

## Acceptance criteria

1. Architecture and intended operator/consumer journeys are summarized from current sources of
   truth and reconciled with the live runtime.
2. All repository-applicable automated checks are executed with exact results; every skipped or
   unavailable check is named.
3. The locked Playwright gate runs against its guarded disposable fixture.
4. The running local application is exercised in a real browser across the applicable section 10
   matrix, including 390, 900 and 1440 px layout checks and browser console/network review.
5. At least one bounded supplied PDF is exercised through the supported document-set ingestion and
   RAG preparation path, or the exact unmet prerequisite is recorded before downstream claims.
6. Authentication, authorization denial, same-tenant scope and cross-tenant behavior are tested
   without weakening server-side controls.
7. REST/MCP/health/metrics and representative runtime/idempotency behavior are tested when their
   configured prerequisites are available.
8. `verification.md` contains pass/fail/blocked results, UX findings, security/operations review,
   assumptions, retained test state and remaining risks.

## Affected components

- Documentation only: this plan, threat model and verification record.
- Exercised runtime: `apps/console`, `apps/documents`, `apps/ingestion`, `apps/retrieval`,
  `apps/evaluations`, `apps/releases`, `apps/gateway`, `apps/mcp`, `apps/observability`,
  `apps/workflows`, `apps/agents`, `apps/tools`, the React workflow builder, PostgreSQL/pgvector,
  Redis, MinIO and Celery roles.

## Interfaces affected

No product interface is changed. Existing console, REST, MCP, metrics and worker interfaces are
observed and exercised.

## Data impact

The assessment may create synthetic local organizations, identities, documents, immutable
versions, indexes, releases, runs, usage and audit rows. Supplied PDFs remain unchanged. No reset or
physical purge is authorized. Retained synthetic state is listed in `verification.md`.

## Security impact

The assessment crosses authentication, CSRF, bearer-token, object authorization, tenant isolation,
file upload, provider readiness, release and audit boundaries. Credentials, cookies, tokens,
document text, prompts and provider responses must not enter the report or captured evidence.

## Authorization impact

No authorization logic changes. Tests cover an authorized exact-responsibility actor, a same-tenant
actor without the responsibility, a neighboring responsibility and a foreign-tenant actor where
fixtures permit.

## Observability impact

No telemetry code changes. Health, safe error behavior, request correlation, metrics and redacted
audit evidence are inspected. Raw sensitive payloads are not copied into evidence.

## Migration impact

No migration is authored by this QA task. The current uncommitted migration and database migration
state are checked; schema changes are not applied outside the repository-supported non-destructive
stack lifecycle.

## Dependencies

- Healthy canonical Docker Compose roles and current bind-mounted source.
- Python 3.13 repository environment or the documented container fallback.
- Locked frontend dependencies and an installed Chromium-compatible browser.
- Existing deterministic providers for hermetic coverage; governed live-provider capabilities are
  conditional on approved local configuration.

## Implementation steps

1. **Baseline and architecture:** inspect plans, handoff, guides, URLs, models/services, tests,
   working-tree diff and live service/health/worker state.
2. **Safe current build:** run frontend dependency/build checks and refresh only the non-destructive
   local stack roles needed to ensure workers execute current code.
3. **Static and automated gates:** run Ruff format/lint, mypy, Django system/migration checks,
   compileall, full SQLite tests, applicable PostgreSQL tests, frontend unit tests and build.
4. **Locked browser regression:** run `npm run test:browser` against the guarded disposable database.
5. **Live functional/API checks:** exercise health/readiness, session auth, REST/MCP protocol
   separation, idempotency, safe denial/error envelopes, worker-backed flows and observability.
6. **Document/RAG journey:** use a bounded supplied PDF to test upload, draft, publish, staged build,
   promotion and retrieval, stopping honestly at the first unmet governed prerequisite.
7. **Manual browser/UX gate:** exercise affected and adjacent journeys with matched roles, direct
   negative probes, console/network review, keyboard use and 390/900/1440 px checks.
8. **Review and reporting:** review evidence as staff engineer, AppSec and SRE; write findings and
   residual risks without modifying product code.

## Test plan

| Layer | Coverage |
| --- | --- |
| Static | Formatting, lint, typing, Django checks, migration drift, bytecode compilation |
| Unit/integration | Full Python suite plus PostgreSQL/pgvector/RLS-sensitive coverage |
| Frontend | Typecheck, Vitest, production bundle |
| Browser automation | Guarded Playwright role, route, lifecycle and regression subset |
| Live browser | Console journeys, role affordances, direct-denial parity, responsive/keyboard UX |
| Consumer contracts | Health, REST Responses/Chat, background run/idempotency, MCP separation, metrics |
| RAG | PDF upload, immutable set version, staged/active index, retrieval and grounded response where ready |
| Security/operations | Tenant isolation, safe errors, audit redaction, worker readiness and bounded logs |

## Rollout plan

Documentation-only. No production rollout. The live local stack may be non-destructively rebuilt or
restarted to load current code; any such action is recorded.

## Rollback plan

Documentation can be reverted independently. Existing application data is preserved. Synthetic
records are retained unless a separate safe cleanup is clearly reversible and does not delete
pre-existing data.

## Risks

- The dirty worktree contains another agent/user's uncommitted implementation; tests may reveal
  failures that cannot be attributed to the base commit alone.
- Bind-mounted web code can be current while long-running Celery workers still execute an older
  import snapshot; workers must be refreshed before live async claims.
- Real provider/LDAP/external connector paths may be unavailable by design; downstream lifecycle
  coverage must be marked blocked, not passed.
- Uploading supplied PDFs creates retained local object-store/database data; reports must identify
  it without reproducing document content.
- Broad automated suites and browser flows may take significant time; partial completion is not a
  pass.

## Open questions

- Whether approved live model/embedding/OCR/connector profiles are configured is determined from
  safe readiness projections, never by exposing their secret material.
- Destructive tombstone/purge/reset paths remain excluded unless the owner explicitly expands scope.

## Status

**Implemented; product verification failed.** The assessment and evidence record are complete.
The current application is not `Verified` because the mandatory browser gate, mypy, live KAP RAG
path and identified security/observability controls have open findings. See `verification.md`.

## Outcome

- Architecture, roles, data flow and supported operator/consumer journeys were reconciled with
  live runtime state.
- Automated backend, PostgreSQL/pgvector, frontend and browser suites were run and recorded.
- A separate deterministic 64-dimensional index proved the supplied-PDF RAG lifecycle can succeed
  end to end without changing the existing KAP served index.
- The existing KAP active index failed retrieval because its 1,536-dimensional geometry does not
  match the configured 64-dimensional runtime embedder.
- Product code was not changed; eight prioritized findings and retained local QA state are recorded
  in `verification.md`.
- The plan remains unarchived because product remediation, rerun evidence and required human review
  are outstanding.

## Completion criteria

- Acceptance criteria map to recorded evidence.
- Applicable automated and browser gates have explicit results.
- Security, authorization, privacy, observability, migration and operations impacts are reviewed.
- Findings, unverified assumptions, retained test state and manual-review needs are explicit.
