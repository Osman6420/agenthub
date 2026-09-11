# Verification: Phase 2.9 Part 7

## Outcome

Completed and verified on 2026-08-02. The deterministic browser, repository quality and manual UX
gates pass. Part 5's configured live Gemini/browser acceptance is a separate deployment prerequisite
and is not claimed here.

## Browser, authorization and security evidence

- A guarded launcher creates a unique `.tmp/agenthub_browser_gate_*.sqlite3` fixture locally; CI
  accepts only a local PostgreSQL database named with the `agenthub_browser_gate` prefix. Unsafe
  SQLite and canonical PostgreSQL names were both rejected before connection or mutation.
- Six real Edge/Chromium journeys cover exact viewer/editor/releaser/runtime/content-reader/
  document-manager duties, unassigned and foreign-tenant denial, same-tenant sibling denial,
  provider-disabled Studio guidance, scenario callability, active exact set/index/profile retrieval,
  direct forbidden lifecycle POST, keyboard skip focus and a 390 px viewport without page overflow.
- Browser state is isolated per test. CI retains only failure screenshots and bounded redacted JSON
  containing role, safe path, console/network category/status and up to ten request IDs. HAR, video,
  trace, DOM, headers, cookies, credentials, token values and bodies are not collected.
- The retrieval browser proof uses the existing deterministic demo provider only in guarded browser
  settings. PostgreSQL/RLS tests separately prove database enforcement; no live pgvector/provider
  or external egress is claimed.
- `npm audit --audit-level=moderate` reports zero vulnerabilities after exact dev-tool upgrades.

## Automated checks

- Real browser, local installed Edge, current production build: `6 passed` in 35.8 s.
- Frontend Vitest: `33 passed`; TypeScript typecheck passed; Vite 8.2.0 production build passed.
- Backend focused authorization/type-change set: `160 passed, 7 skipped`; dashboard-focused
  regressions: `28 passed`; manual-review fixes: `16 passed`; timestamp regression: `5 passed`.
- Full SQLite: `1102 passed, 61 skipped` in 208.89 s; skips are declared PostgreSQL/pgvector/RLS/
  row-lock cases.
- Existing PostgreSQL test database with `--reuse-db`: `56 passed, 3 SQLite-only skipped` for
  assignment, tenancy, kill-switch, runtime-control, tool-approval and Part 6 exact-content/RLS
  adjacency.
- Full mypy: no issues in `454 source files`.
- Ruff lint passed; Ruff format reports `460 files already formatted`.
- Django system check passed; `makemigrations --check --dry-run` reported no changes.
- CI workflow YAML parsed and contains the isolated browser job; the job itself has not yet run on
  GitHub Actions.

## Review

- Staff engineering: one cross-platform launcher owns fixture setup; Playwright uses semantic
  selectors and a single worker; the browser job gates production image builds.
- Application security: disposable-database guards, direct server denial, exact-scope assertions,
  provider no-egress configuration and bounded failure-only evidence were reviewed against the
  threat model.
- SRE: no schema or production runtime dependency was introduced. CI browser downloads are isolated
  to the browser job; artifacts expire after seven days; rollback is code/config removal.

## Manual UX evidence

- At 390 px the exact viewer had no horizontal overflow, the skip link/focus path worked, and the
  dashboard no longer exposed runtime or decision cards absent from its responsibility navigation.
- At 900 px the content reader saw only home/documents, without overflow; the governed document-set
  creation reason now names the exact `organization_admin` duty.
- At 1440 px the scenario editor saw clear Scenario/Studio affordances, writable controls and the
  provider-disabled explanation without overflow or console warnings/errors; release timestamps use
  the locale-stable `d.m.Y H:i` presentation.
- The review discovered and closed tenant-wide pending-decision/dashboard affordance leakage for
  exact roles. Destination authorization remained deny-by-default and direct denial is automated.

## Remaining acceptance

- The GitHub-hosted CI job is configured and locally parsed but has not yet executed remotely.
- Part 5 configured live Gemini/provider browser acceptance remains open and is not part of this
  completed deterministic/no-egress gate.
