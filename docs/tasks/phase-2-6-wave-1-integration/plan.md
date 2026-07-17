# Task Plan: Phase 2.6 first-wave integration

## Objective

Integrate the completed first-wave branches into `feat/foundation-sprint-0-1`, resolve only
cross-branch conflicts, rerun combined verification, and preserve the independent activation gates
for P2.6.7, P2.6.8 runtime, and P2.6.9 Python-node catalog integration.

## Scope

- Confirm P2.6.7 is already an ancestor of the integration branch.
- Merge P2.6.8 isolation spike, P2.6.1 typed state mapping, P2.6.9 Studio authoring context, and
  P2.6.10 ingestion lifecycle in dependency order.
- Resolve ADR and documentation allocation collisions without weakening either decision.
- Fix integration-only format, typing, and test-contract failures.
- Run focused and repository-wide SQLite, PostgreSQL/pgvector/RLS, frontend, static, Django, and
  migration checks.

## Exclusions

- P2.6.7 live catalog synchronization implementation or activation.
- P2.6.8 Python-node control plane or isolated runtime implementation.
- P2.6.9 integration with a future active Python-node public catalog.
- Starting P2.6.2, P2.6.3, or P2.6.5.

## Acceptance criteria

1. Every completed first-wave commit is reachable from the integration branch.
2. ADR identifiers and migration identifiers are unique and referenced correctly.
3. Combined compiler, builder, authoring, ingestion, console, authorization, and tenant tests pass.
4. SQLite and applicable PostgreSQL/pgvector/RLS profiles have recorded evidence.
5. Ruff, mypy, Django checks, migration drift, frontend tests/build, and diff checks pass.
6. Remaining activation and implementation gates are explicit.

## Status

Implemented and verified on 2026-07-17. Evidence is in [`verification.md`](verification.md).
