# AgentHub — Phase 3 Plan (DISCOVERY)

> **Status: DISCOVERY ONLY.** Personal MCP identity and on-behalf-of delegation moved from Phase 2
> to Phase 3 by owner decision on 2026-07-14. This document records discovery inputs; it does not
> authorize authentication, authorization, IAM, token, network or downstream production changes.

## Purpose

Design personal/end-user MCP calls such as “grant my access” or “get my payroll” with verified user
identity, least-privilege delegation to downstream systems and complete effective-actor audit.

## Decisions required before implementation

1. Identity source and protocol: institutional OIDC, SAML bridge, LDAP/directory synchronization or
   another approved IdP; token issuer, audience, signing and claim contract.
2. OBO format: standards-based token exchange or downstream-specific short-lived token, scopes,
   lifetime, revocation and replay defenses.
3. Downstream trust: ERP and other service verification contract, capability matrix, impersonation
   boundaries, service-account fallback rules and failure behavior.
4. Authorization: normalized group claims, nested/fresh membership resolution, time-bounded user
   exceptions, tenant/object/action/field enforcement and deny-by-default behavior.
5. Audit/privacy: authenticated actor, effective actor, impersonating service, purpose, target,
   decision/outcome, retention and redaction.

## Discovery inputs retained from Phase 2

- Prefer OIDC access tokens where the institution supports them; LDAP/AD may remain the directory.
- Prefer group-first grants and time-bounded user exceptions.
- Prefer short-lived scoped per-downstream OBO/token exchange; signed identity propagation is the
  next option, with service-account plus platform ACL only as a constrained fallback.
- Build a downstream capability and trust matrix before selecting the contract.
- Upstream ACL preservation for service-account-fetched content remains a proposed requirement.

## Required planning artifacts

Before implementation, create a dedicated task plan, identity/data-flow diagram, abuse-case threat
model, ADRs for IdP/OBO/downstream trust, compatibility/rollout/rollback plan and negative test matrix.

## Status

Discovery; no implementation approval or completion date assigned.
