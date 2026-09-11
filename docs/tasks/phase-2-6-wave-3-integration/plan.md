# Task Plan: Phase 2.6 activation-closure wave integration gate

## Objective

Close the integration gate for the merged P2.6.7 MCP activation closure, P2.6.8 OpenShift
fixed-pool runner, P2.6.9 Studio AI activation and P2.6.10 ingestion activation-closure branches
on `codex/p2-6-activation-integration`, then land the verified head on
`feat/foundation-sprint-0-1`.

## Scope

- Confirm the integration head contains exactly the four activation branches merged onto the wave
  base `7f18a26` with no dropped sibling change.
- Run repository static gates and the full SQLite regression suite on the merged tree.
- Run the full PostgreSQL/pgvector regression profile (fresh `--create-db`, MCP/metrics enabled),
  which applies the merged migration graph including the new `tools.0003` catalog-sync migration.
- Run the frontend gates (`npm ci`, `tsc --noEmit`, `vitest`, `vite build`) because P2.6.9 changed
  the Studio SPA.
- Record evidence in this task's `verification.md`; update the Phase 2.6 plan status, the
  repository verified-state section and the master plan; fast-forward
  `feat/foundation-sprint-0-1`.

## Exclusions

- No production activation: MCP catalog-table application-role grants stay unapproved
  (P2.6.7 remains activation-blocked), `PYTHON_NODE_RUNNER_ATTESTED` stays unset (P2.6.8 runner
  inactive), and ingestion/runtime defaults are unchanged.
- No destructive reset of the developer database or persistent Compose volumes.
- No live MCP server, OpenShift cluster, or live model egress.
- No browser-driven Studio journey; that remains final Phase 2.6 acceptance work.

## Acceptance criteria

1. All four activation branch tips are ancestors of the integration head and their delivered files
   are unmodified by the merges except recorded conflict resolutions.
2. Ruff format/lint, mypy, Django system check, migration-drift check and `compileall` pass on the
   merged tree.
3. The full SQLite regression suite passes.
4. The full PostgreSQL regression profile passes on a fresh test database that applies the complete
   merged migration graph (including `tools.0003`), with MCP/metrics test surfaces enabled.
5. Frontend type-check, unit tests and production build pass from a clean `npm ci`.
6. Phase 2.6 status, the repository verified-state section and the master plan reflect the
   integrated wave; `feat/foundation-sprint-0-1` fast-forwards to the verified head.

## Risks

- The shared repository `.venv` previously failed to launch for one session
  (Microsoft Store launcher); fallback is the manual-guide disposable container.
- Long full-suite runs must not be truncated by command timeouts; run in background with log
  polling per testing rules.
- Parallel sessions may hold Compose services and workers; this gate only reads live state and
  creates disposable test databases, never stopping other sessions' processes.

## Status

Implemented and verified on 2026-07-17. Evidence is recorded in
[`verification.md`](verification.md). The owner approved the P2.6.7 catalog-table application-role
grants at this gate; P2.6.6 is the next implementation part.
