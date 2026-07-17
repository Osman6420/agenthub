# ADR 0012: Durable ingestion build jobs and compatible-worker readiness

- **Status:** Accepted
- **Date:** 2026-07-16

## Context

The document-set console previously published a Celery task directly. `IndexVersion` was created
only after a worker claimed that task, so a broker-accepted request could have no durable product
state and the UI could not distinguish a compatible consumer from a reachable broker.

## Decision

- PostgreSQL is authoritative for `StagedIndexBuildJob`, its identifier-only dispatch outbox and
  bounded ingestion-worker heartbeat evidence. Redis/Celery is delivery only.
- Job request checksum, organization, set/profile lineage and pipeline fingerprint are immutable.
  A partial unique constraint permits only one active equivalent build.
- The canonical states are `dispatch_pending`, `queued`, `running`, `retry_wait`, `succeeded`,
  `failed`, `cancelled` and `reconciliation_required`. Row locks, legal service transitions and
  terminal guards make claim, redelivery and late results idempotent.
- Job and outbox intent commit atomically. A bounded dispatcher/reconciler republishes unpublished
  intents and carries only the opaque job UUID in the Celery body; tenant lineage is a trusted
  message header and is revalidated against the row.
- Workers record an opaque instance UUID, contract/service revision and SHA-256 of non-secret
  normalized configuration. Credentials contribute only a presence bit. A heartbeat counts only
  while recent and exactly contract/config compatible.
- Public web readiness remains unchanged. Ingestion compatibility is exposed through an operator
  preflight, bounded metrics and coarse tenant console state, so ingestion degradation does not
  incorrectly fail synchronous query readiness.
- Retry is bounded and never automatic for ambiguous provider/OCR outcomes. Exact promotable-index
  lineage may reconcile a lost final job update; otherwise the job requires operator reconciliation.
- A successful build remains merely promotable. Existing release-manager authorization is still
  required for activation.

## Security and data consequences

Job and outbox rows carry direct organization lineage and PostgreSQL FORCE RLS. They store no
document content, filenames, endpoints, credentials or raw exceptions. Metrics labels are limited
to bounded state, failure class and compatibility; tenant, job, document and worker IDs are not
labels. Audit remains content-free and uses opaque job/index references.

## Operational consequences

Compose and host mode share broker/object-store/revision inputs and the same preflight. Celery beat
dispatches the reconciler every 30 seconds in bounded batches. Rollback may stop new dispatch but
must retain job/outbox/audit evidence and run code compatible with in-flight contract revision 1.

## References

- [P2.6.10 plan](../tasks/phase-2-6-ingestion-operational-lifecycle/plan.md)
- [Threat model](../tasks/phase-2-6-ingestion-operational-lifecycle/threat-model.md)
- [ADR 0008](0008-durable-workflow-transition-state-machine.md)
