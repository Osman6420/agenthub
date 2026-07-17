# Verification — P2.6.10 ingestion activation closure

## Status

Not started. Populate this record only from checks and live drills run on the exact Phase 2.6
integration commit used for closure.

## Required evidence

- Exact commit and migration state.
- Static, focused SQLite and PostgreSQL/FORCE-RLS results.
- Canonical Compose and bounded worker/process state before and after drills.
- Preflight results for absent/stale/mismatched and compatible workers.
- Synthetic durable job/outbox/index lifecycle and no-promotion proof.
- Worker absence/restart, duplicate/redelivery and reconciliation results.
- Audit, redaction, metric-label and final runtime-state review.
- Checks not run, residual risks and staff/security/SRE final review.
