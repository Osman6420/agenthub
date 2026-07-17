# Task Plan: Phase 2.6 second-wave integration gate

## Objective

Close the integration gate for the merged P2.6.2 parallel/join, P2.6.3 durable waits, P2.6.5
child composition and P2.6.8 isolated Python-runtime seam before P2.6.4 begins.

## Scope

- Verify the merged migration chain `workflows.0004` through `workflows.0006` on PostgreSQL.
- Run PostgreSQL RLS and cross-tenant proofs for branch, join, wait and child-link state.
- Verify cancellation, duplicate delivery, late result and timer recovery behavior across the merged
  runtime state machine.
- Run repository static checks and the combined backend regression suite.
- Update Phase 2.6 status and record evidence without activating child composition or Python nodes.

## Exclusions

- Destructive reset of the developer database or persistent Compose volumes.
- P2.6.4 retry/compensation implementation.
- Production activation of P2.6.7, P2.6.8, P2.6.9 or P2.6.10.
- P2.6.6 agentic-loop implementation.

## Acceptance criteria

1. The PostgreSQL test database applies the complete migration graph with no drift.
2. Direct tenant tables added in this wave are present in RLS inventory/provisioning and cross-tenant
   access is denied where a database-level proof exists.
3. Parallel, wait and child lifecycle tests cover cancellation, idempotency, late results and
   bounded recovery, and pass together.
4. Ruff, format, mypy, Django system checks and the repository regression suite pass or have an
   explicitly recorded environment-only limitation.
5. P2.6.8 remains fail-closed without an approved resolver/runner; P2.6.5 remains disabled by
   default.
6. Phase 2.6 status identifies P2.6.4 as the next implementation part.

## Status

Implemented and verified on 2026-07-17. Evidence is recorded in
[`verification.md`](verification.md). P2.6.4 is the next implementation part.
