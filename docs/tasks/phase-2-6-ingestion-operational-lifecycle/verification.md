# Verification — Phase 2.6 ingestion operational lifecycle

## Current result

Planning complete; implementation has not started. Runtime gap evidence is the
[2026-07-16 local smoke](../local-document-ingestion-smoke-2026-07-16/verification.md).

| Check | Result | Evidence |
| --- | --- | --- |
| Staged dispatch/model inspection | Pass | Console dispatches directly; `IndexVersion` lifecycle begins inside worker |
| Health/readiness inspection | Pass | Ready checks database, migrations and Redis only |
| Compose/host parity inspection | Gap recorded | Compose has ingestion worker/object-store env; host guide lacks equivalent setup |
| Live observation | Informational | Compose PostgreSQL/Redis/MinIO healthy; host web liveness 200; no Compose app workers |
| Documentation whitespace check | Pass | `git diff --check` on 2026-07-16 |
| Implementation tests | Not run | Planning-only task |

## Required implementation evidence

- SQLite lifecycle/authz/redaction tests.
- PostgreSQL pgvector concurrency, constraint, non-owner FORCE RLS and reconciliation tests.
- Real Redis/Celery/MinIO `.txt` smoke plus worker/broker/crash/config-drift drills.
- Migration drift, formatter, lint, type, full tests, secret scan and final-diff review.
- Metrics cardinality, audit completeness/redaction, trace and alert evidence.

No process was started/stopped/reconfigured during planning. Host web liveness does not prove an
ingestion consumer. Thresholds, heartbeat authority and provider retry classes remain ADR decisions.

## Status

Planned, not implemented or verified.
