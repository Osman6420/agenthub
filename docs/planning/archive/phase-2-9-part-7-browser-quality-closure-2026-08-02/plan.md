# Task Plan: Phase 2.9 Part 7 Browser and Quality Closure

## Objective

Close Phase 2.9 with a deterministic real-browser role/authorization gate, redacted failure
evidence, a clean owned Ruff-format/mypy baseline, and a documented manual UX acceptance pass.

## Scope

- Add Playwright as a frontend development/test dependency only; no production package or runtime
  browser dependency is introduced.
- Build a disposable synthetic browser fixture and server launcher isolated from developer/live
  data. Never seed, flush or reset the canonical local database.
- Exercise login, responsibility-aware navigation, direct allow/deny, same-tenant cross-scope,
  cross-tenant, scenario callability, served index/retrieval state, release/runtime controls and
  provider-disabled Studio guidance in a real browser.
- Capture bounded screenshot, URL, role, request ID and console/network failure evidence only on
  failure. Do not capture document bodies, tokens, passwords, cookies, object keys or secrets.
- Wire the gate into CI with a disposable PostgreSQL service and locked Node/Python dependencies.
- Fix the current mypy production/test typing errors and Ruff-format deviations without changing
  authorization or runtime behavior.
- Execute and record the manual Turkish UX, keyboard, focus and responsive review where the current
  environment permits it.
- Reconcile any browser-discovered role/metric mismatch before closure. The 390 px viewer pass found
  that dashboard operation/decision links remained visible after their navigation entry was hidden,
  and pending tool/human-task counts were tenant-scoped rather than capability-scoped. Make these
  cards deny-by-default without weakening the destination authorization checks.

## Trust boundaries and data flow

The browser, URL/query strings, DOM, screenshots, console logs and network events are untrusted.
The fixture database is disposable and must be selected by an explicit browser-gate database URL.
The launcher refuses the canonical `agenthub` database and any non-loopback database host. Browser
credentials are synthetic test-only values. Existing server-side scope/capability checks remain the
authorization source of truth; browser assertions prove affordance parity but grant no authority.

## Implementation

1. Inventory live stack, current CI, browser availability, format and mypy baselines.
2. Add locked Playwright dev tooling, a cross-platform disposable server/fixture launcher and stable
   `data-testid` selectors only where role/name selectors are insufficient.
3. Add role-matrix and lifecycle/retrieval browser specs with bounded failure evidence.
4. Add an isolated CI browser job and local command/runbook documentation.
5. Close all reported mypy and Ruff-format deviations with mechanical or type-only changes backed
   by the existing full suites.
6. Run browser, SQLite, PostgreSQL/RLS, frontend/type/build/format/lint/mypy/schema checks and the
   manual UX pass; record evidence, update plans, archive and commit.

## Non-goals / approval boundaries

- No production dependency, browser in application images, auth/role/capability/public API/schema
  change, live-provider call, production access or destructive canonical-database operation.
- No screenshots on success and no blanket tracing/HAR/video containing business data.
- Part 5's configured live Gemini acceptance remains a separate deployment prerequisite; Part 7
  covers the provider-disabled and safe-error browser state without claiming a live model pass.

## Rollback

Remove the browser test package/config/fixtures and CI job; revert type/format-only changes. No
production state, audit history, release, index pointer or stored content changes.

## Risks

Accidental live DB mutation, browser evidence leakage, brittle selectors, timing flakes, CI browser
download instability, authorization assertions that only hide UI, type-only edits changing runtime,
and a false manual-pass claim. Controls are an explicit disposable DB guard, synthetic fixtures,
failure-only redacted evidence, semantic selectors, bounded waits, direct URL probes, full regression
tests and explicit reporting of any manual/browser environment limitation.

## Status

Completed and verified on 2026-08-02. The guarded six-journey browser gate passes on local Edge,
CI is wired for disposable PostgreSQL/Chromium, full mypy and Ruff are clean, the frontend audit is
clean, and SQLite/PostgreSQL regressions pass. The manual Turkish UX, keyboard and responsive pass
at 390, 900 and 1440 px found and closed dashboard scope/affordance, role-reason and timestamp
presentation defects. Part 5's configured live-provider acceptance remains a separate deployment
prerequisite. See `verification.md`.
