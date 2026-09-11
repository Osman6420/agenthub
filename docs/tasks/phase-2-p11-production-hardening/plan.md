# P11 index: PostgreSQL tenant-isolation hardening

## Purpose

This page is the stable, discoverable P11 entry point. It does not duplicate the authoritative
Phase 2 closure plan or its evidence:

- [Closure plan](../phase-2-closure-production-hardening/plan.md)
- [P11 verification evidence](../phase-2-closure-production-hardening/verification.md)
- [RLS deployment runbook](../../operations/phase-2-app-role-rollout.md)

P11 was delivered as the first implementation increment of the broader Phase 2 production-closure
task. The closure task still owns environment-specific live-profile activation, so its existing
directory remains the source of truth. Upload scanning moved to
[Phase 3](../../planning/phase-3-plan.md) by owner decision on 2026-07-14.

## P11 scope and status

- **P11.1 — inventory/readiness:** implemented and offline-verified.
- **P11.2 — direct tenant lineage and transaction-local context:** implemented and verified on
  SQLite and PostgreSQL.
- **P11.3 — canonical FORCE RLS:** implemented and staging-equivalent verified; production
  migration/application remains explicitly deployment-gated.
- **P11.4 — least-privilege non-owner role:** provisioning and rollback SQL are implemented and
  staging-equivalent verified; production role/secret activation remains explicitly
  deployment-gated.

P11 requires no further planned application-code implementation. Production pooler validation,
role/secret provisioning, migration execution, monitoring and rollback evidence are deployment
activities and remain open in the closure plan.

## Remaining Phase 2 boundary

P11 requires no further application-code implementation. The separately planned
[Phase 2.5 product-coherence milestone](../../planning/phase-2-5-plan.md) now precedes
environment-specific provisioning, live-profile activation and live smoke/rollback closure.
Governed upload malware/type scanning and all of its fail-closed, limit, audit, test and runbook
requirements are Phase 3 scope.
