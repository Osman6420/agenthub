# Task Plan: Phase 2 closure production hardening

## Task summary

Close Phase 2 with the production controls and live-profile evidence that remain intentionally
outside the offline-verified implementation: broader Django-table RLS with a dedicated non-owner
application role, governed upload malware/type scanning, live Confluence/REST/embedding/OCR
profiles, and live AI-authoring activation and smoke evidence.

## Owner decisions (2026-07-14)

- This work is part of Phase 2 and is required before Phase 2 closes.
- AI authoring live activation is performed at the Phase 2 closure milestone, not earlier.
- Personal MCP identity/delegation is not a Phase 2 dependency; it moves to Phase 3.

These decisions authorize planning and sequencing. They do not invent or approve concrete secrets,
hosts, certificates, firewall rules, production data access, scanner products/dependencies, or
irreversible database operations. Each concrete environment change still requires its named input,
change record, rollback plan and explicit execution approval under `AGENTS.md`.

## Scope and acceptance criteria

- [ ] Enumerate Django-managed tenant tables and apply deny-by-default PostgreSQL RLS policies with
  transaction-local tenant context; prove missing/invalid/cross-tenant context denial.
- [ ] Provision a dedicated non-owner, non-superuser application role without `BYPASSRLS`; verify
  web and worker paths use it and table owners are not used by the application.
- [ ] Select and approve an upload malware/type scanning boundary; quarantine or reject before
  content becomes indexable, with bounded files/timeouts and redacted audit.
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
- Scanner failure policy must be explicit and fail closed for indexing; scanner content, signatures
  and file samples must not enter application logs.
- Live profiles introduce confidential-data egress, provider retention and denial-of-wallet risks.
- A post-send model/embedding/OCR uncertainty is terminal and is never blindly retried.
- Production smoke tests must use approved synthetic/non-production data unless production-data
  access receives separate explicit approval.

## Implementation sequence

1. Inventory tables, roles, connection paths and current RLS ownership; produce reversible SQL and
   deployment-role design consistent with ADR-0004.
2. Threat-model and select the upload scanner/dependency or external service; obtain dependency and
   egress approval before implementation.
3. Implement and verify RLS/role and scanning changes in local PostgreSQL and a staging-equivalent
   environment.
4. Collect concrete profile, secret, CA, DNS/firewall, privacy/retention and cost inputs.
5. Activate connector/embedding/OCR profiles with bounded synthetic smoke tests and rollback proof.
6. Activate AI authoring last; run the governed candidate flow and immediately verify disable/rollback.
7. Run full gates, record production-readiness evidence and close Phase 2 only after manual sign-off.

## Migration and rollback

RLS/ownership changes require a staged reversible migration or deployment SQL reviewed against the
exact PostgreSQL role topology. Upload scanning must be feature-gated with quarantine preserved.
Every live profile is disabled by status/config rollback; unset `AI_AUTHORING_MODEL_PROFILE_ID` to
disable AI authoring without changing existing drafts.

## Status

Planned for Phase 2 closure; concrete environment inputs and per-change execution approvals pending.
