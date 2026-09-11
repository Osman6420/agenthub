# Task Plan: Phase 2 closure production hardening

## Task summary

Close Phase 2 with the production controls and live-profile evidence that remain intentionally
outside the offline-verified implementation: broader Django-table RLS with a dedicated non-owner
application role, live Confluence/REST/embedding/OCR profiles, and live AI-authoring activation and
smoke evidence.

## Owner decisions (2026-07-14)

- This work is part of Phase 2 and is required before Phase 2 closes.
- AI authoring live activation is performed at the Phase 2 closure milestone, not earlier.
- Personal MCP identity/delegation is not a Phase 2 dependency; it moves to Phase 3.
- Governed upload malware/type scanning, including quarantine/rejection, fail-closed behavior,
  limits, redacted audit, tests and runbook, moves to Phase 3.
- Phase 2.5 product-coherence implementation and verification must complete before live activation
  and final Phase 2 closure acceptance begin.

These decisions authorize planning and sequencing. They do not invent or approve concrete secrets,
hosts, certificates, firewall rules, production data access, or
irreversible database operations. Each concrete environment change still requires its named input,
change record, rollback plan and explicit execution approval under `AGENTS.md`.

## Scope and acceptance criteria

- [x] Enumerate Django-managed tenant tables and apply deny-by-default PostgreSQL RLS policies with
  transaction-local tenant context; prove missing/invalid/cross-tenant context denial.
- [x] Provide and staging-verify dedicated non-owner, non-superuser application-role provisioning
  without `BYPASSRLS`; verify operator middleware and identifier-bound worker context under the
  non-owner boundary. Production role/secret activation remains deployment-gated.
- [ ] Register and validate concrete live Confluence and generic REST profiles, credentials, CA/DNS
  and firewall policy; run bounded non-production-data smoke tests before any production corpus.
- [ ] Register and validate concrete embedding and OCR profiles with privacy/retention, token/cost,
  timeout, response-size and no-blind-retry controls.
- [ ] Register the real AI-authoring `ModelProfile`, configure `AI_AUTHORING_MODEL_PROFILE_ID`,
  approve privacy/retention and spend ceilings, and execute candidate → diagnostics → explicit
  draft-transfer smoke evidence without publish/release side effects.
- [ ] Record rollback/disable procedures, monitoring, audit evidence and residual-risk acceptance.

## Security and operational risks

- Incorrect RLS rollout can deny all traffic or expose cross-tenant rows; use staged policy rollout,
  non-owner negative tests and connection-pool context-leak tests.
- Live profiles introduce confidential-data egress, provider retention and denial-of-wallet risks.
- A post-send model/embedding/OCR uncertainty is terminal and is never blindly retried.
- Production smoke tests must use approved synthetic/non-production data unless production-data
  access receives separate explicit approval.

## Implementation sequence

1. Complete and verify the authoritative
   [Phase 2.5 product-coherence plan](../../planning/phase-2-5-plan.md).
2. Inventory tables, roles, connection paths and current RLS ownership; produce reversible SQL and
   deployment-role design consistent with ADR-0004.
3. Implement and verify RLS/role changes in local PostgreSQL and a staging-equivalent environment.
4. Collect concrete profile, secret, CA, DNS/firewall, privacy/retention and cost inputs.
5. Activate connector/embedding/OCR profiles with bounded synthetic smoke tests and rollback proof.
6. Activate AI authoring last; run the governed candidate flow and immediately verify disable/rollback.
7. Run full gates, record production-readiness evidence and close Phase 2 only after manual sign-off.

## Increment P11.1: RLS deployment-readiness inventory

Status: **implemented and offline-verified**.

The first offline increment does not enable policies or change a deployed database role. It adds a
deterministic inventory of Django tables with a direct tenant column and a PostgreSQL readiness
check for the proposed application role. The check must fail when a table is missing `ENABLE` or
`FORCE ROW LEVEL SECURITY`, when the canonical policy is absent, or when the proposed role is a
superuser, has `BYPASSRLS`, owns a protected table, or lacks required read access. Table-specific
write grants remain a separate least-privilege design; P11.1 never requires blanket write/delete.

This sequencing is required because current operator views can intentionally aggregate several
membership-authorized organizations in one request, while ADR-0004 carries one transaction-local
tenant id. Policy activation remains a later increment: each web/worker path must first have an
explicit trusted context/bootstrap design and PostgreSQL negative evidence. The readiness command
is diagnostic only and must not create roles, grant privileges, alter tables or set tenant context.
Operational usage and classification semantics are documented in
[`phase-2-rls-readiness.md`](../../operations/phase-2-rls-readiness.md).

P11.1 deliberately leaves policy activation, schema denormalization, request/worker context
propagation and application-role provisioning open. Nine relationship-only tenant tables are
reported as blockers rather than silently omitted. Evidence is recorded in `verification.md`.

## Increment P11.2–P11.4: RLS activation and deployment role

Status: **implemented and staging-equivalent verified; production activation pending**.

- Add an immutable, non-null direct `organization_id` lineage column to the nine indirect tenant
  tables, backfilled from their authoritative parent and checked on every application write.
- Use a transaction-local, server-derived tenant scope: operator requests receive the exact active
  membership set; gateway authentication narrows it to the authenticated consumer organization;
  worker messages carry both object id and authoritative organization id and re-check both.
- Keep membership and bearer-token lookup as explicit bootstrap tables because tenant identity is
  not known before those lookups. Nullable audit/usage tables retain their separate append/admin
  boundary. These exclusions are visible in readiness output and grant documentation.
- Apply canonical FORCE RLS to protected direct-tenant tables through reversible PostgreSQL-only
  migration DDL. Missing/empty/mismatched context denies rows and writes.
- Provide reviewed provisioning and rollback SQL templates for a non-owner, non-superuser,
  `NOBYPASSRLS` application role. Templates contain placeholders and are not executed against a
  deployment automatically.
- Define table-specific read/write grants; immutable and append-only tables do not receive blanket
  update/delete privileges.

## Migration and rollback

RLS/ownership changes require a staged reversible migration or deployment SQL reviewed against the
exact PostgreSQL role topology. Every live profile is disabled by status/config rollback; unset
`AI_AUTHORING_MODEL_PROFILE_ID` to disable AI authoring without changing existing drafts.

## Status

P11 RLS/non-owner hardening is implemented and staging-equivalent verified. Phase 2 closure remains
in progress: concrete live profiles, production privacy/cost/network inputs and per-change execution
approvals are pending. Phase 2.5 product-coherence development now precedes live closure. Upload
scanning and persistent server-side conversation history are tracked in the Phase 3 plan.
