# Threat Model: Phase 2.6 first-wave integration

## Assets and trust boundaries

- Tenant workflow state, authoring context, document ingestion jobs, release references, audit
  metadata, and PostgreSQL tenant scope remain protected assets.
- AI model output, workflow DSL, document/provider output, broker delivery, and browser input remain
  untrusted.
- The integration must preserve server-side authorization, exact tenant/project/scenario lineage,
  bounded schemas, secret redaction, and PostgreSQL RLS.

## Integration threats and controls

- **Shared-file conflict hides a security check:** merge one branch at a time and rerun combined
  authorization, reference-conformance, redaction, and tenant-isolation tests.
- **Identifier collision changes decision ownership:** retain the already integrated P2.6.8
  ADR-0011 and renumber ingestion ADR to ADR-0012; do not renumber the existing ingestion migration.
- **AI context becomes user authority:** keep system instructions, bounded server context, and user
  text as separate messages; server revalidates all references and lineage.
- **Draft update bypasses project scope:** reject update when project context is absent and verify
  scenario/project lineage before rebuilding live authoring context.
- **Runtime or egress enabled prematurely:** P2.6.8 remains documentation/inert contracts only and
  P2.6.7 has no new implementation delta in this wave.
- **Ingestion redelivery or cross-tenant substitution:** retain durable job/outbox lineage,
  identifier-only task bodies, row locks, tenant header validation, and RLS tests.

## Residual risks

- The local Docker runtime does not satisfy the proposed P2.6.8 production sandbox posture; tenant
  Python execution remains prohibited.
- P2.6.9 cannot expose active Python-node metadata until P2.6.8 publishes and verifies that catalog.
- Real worker crash/restart, broker outage, MinIO failure, and browser acceptance drills remain
  P2.6.10/P2.6.11 operational closure work.
