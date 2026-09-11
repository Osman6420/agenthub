# Threat model — Phase 2.6 ingestion operational lifecycle

## Assets and boundaries

Assets are tenant document/index lineage, job state, object-store authority, provider spend,
promotion authority, audit evidence and operational topology. Boundaries are browser–Django,
Django–PostgreSQL/Redis, broker–worker and worker–MinIO/provider/pgvector. Client progress requests,
Celery delivery and provider errors are untrusted. Broker reachability does not establish a trusted
or compatible worker.

| Threat | Required control/evidence |
| --- | --- |
| Cross-tenant read/retry | Direct organization lineage, server predicates, FORCE RLS, non-owner denial tests |
| Forged transition/result/progress | Server state machine, row lock/CAS, checksum/lineage checks, negative tests |
| Duplicate concurrent builds | Active-job uniqueness, transactional claim, idempotent linking, concurrency tests |
| Commit-to-publish lost request | Durable outbox/reconciler and crash-window test |
| Worker loss/late acknowledgement | Heartbeat expiry, bounded reconciliation, duplicate-delivery convergence |
| Ambiguous external outcome retried | Closed retry taxonomy; reconciliation-required; provider failure drills |
| Stale/config-mismatched worker | Contract/config fingerprint plus TTL; mismatch/stale tests |
| Secret/topology disclosure | Coarse tenant state, operator-only detail, safe errors, redaction tests |
| Resource/cost exhaustion | Rate/active-job/attempt/batch/poll/retention bounds and saturation tests |
| Promotion escalation | Promotable-only result; unchanged release authorization; denial tests |
| Malicious content/error injection | No raw error/content persistence/rendering; allowlisted localized output |
| Heartbeat spoof/replay | Platform worker identity/channel, opaque instance, TTL and contract validation |

Authorization/lineage ambiguity fails closed. Required security/business-audit failure is fail-closed
for retry, cancel, reconciliation and promotion-sensitive actions. Metric/heartbeat failure degrades
readiness and alerts but cannot rewrite a completed result. Only exact lineage/fingerprint evidence
may reconcile a committed index to success.

Residual ADR risks: Redis heartbeat durability versus PostgreSQL write load; provider idempotency;
host multi-process drift; and outbox operational complexity. Direct `on_commit` publish alone leaves
a crash window and cannot meet acceptance.
