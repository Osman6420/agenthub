# Threat model — P2.6.10 ingestion activation closure

## Assets and actors

Assets are tenant documents, job/index lineage, credentials, audit evidence and worker readiness.
Actors are authorized scenario authors/release managers, platform operators, workers and an
untrusted tenant or malformed broker delivery.

## Primary threats and controls

| Threat | Required control and evidence |
| --- | --- |
| Stale feature worker consumes integration tasks | Inspect bounded process state; run exactly one compatible integration-head worker; preflight contract/fingerprint proof |
| Cross-tenant job/index access | Server-side organization predicates, trusted message lineage revalidation and PostgreSQL FORCE-RLS negative test |
| Broker acceptance reported as execution | Durable job/outbox precedes publish; UI/preflight distinguishes queued and compatible consumer |
| Duplicate/redelivered task creates duplicate index | Row locks, immutable checksum, active uniqueness and duplicate/late-delivery tests |
| Worker loss loses accepted work | PostgreSQL-authoritative state, heartbeat timeout and restart/reconciler convergence drill |
| Ambiguous side effect is blindly retried | `reconciliation_required`; retry only locally proven idempotent stages |
| Build success escalates promotion authority | Promotable-only result; no promotion action in smoke; existing release-manager check unchanged |
| Secret/content leaks into evidence or telemetry | Synthetic bounded input; allowlisted errors; content/credential/endpoint/raw-exception absence checks; bounded metric labels |
| Failure drill damages shared local state | No database reset, destructive Redis operation, resource deletion or external provider call; bounded targeted process control |

## Residual risk

Local Windows/Compose drills do not prove production scheduler, network policy, secret manager or
large-scale queue behavior. Environment owners must tune heartbeat retention, alert thresholds and
reconciler sharding before production activation.
