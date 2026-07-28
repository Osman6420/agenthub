# AgentHub — Phase 3 Plan (DISCOVERY / PLANNED)

> **Status: DISCOVERY / PLANNED.** Personal MCP identity and on-behalf-of delegation moved from
> Phase 2 to Phase 3 by owner decision on 2026-07-14. Governed upload malware/type scanning moved
> with its complete safety boundary on the same date. This document records scope and discovery
> inputs; it does not authorize a scanner product/dependency/egress or authentication,
> authorization, IAM, token, network or downstream production changes. Optional multi-agent
> supervision moved from proposed Phase 2.6 to Phase 3 by owner decision on 2026-07-16; it remains
> discovery-only and is not required for Phase 2.6 completion. Phishing-resistant MFA for the
> exceptional Django superadmin recovery identity moved from Phase 2.8 Part 2.1 to Phase 3 security
> hardening by owner decision on 2026-07-24.

## Purpose

Design personal/end-user MCP calls such as “grant my access” or “get my payroll” with verified user
identity, least-privilege delegation to downstream systems and complete effective-actor audit.
Deliver governed upload scanning before treating uploaded bytes as parseable or indexable.
Design optional persistent conversation memory with explicit user/tenant authorization and
retention controls; Phase 2.5 remains client-supplied and stateless.

## Workstream A — Personal MCP identity and delegation

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

## Workstream B — Governed upload malware/type scanning

This is one indivisible security package. It includes malware and content-based type scanning,
quarantine or rejection before parsing/indexing, fail-closed scanner failure behavior, bounded file
size and scanner timeout, content-free/redacted audit, negative and failure-path tests, monitoring,
signature-health policy, retention/purge behavior and an operational rollback/runbook.

Decisions required before implementation:

1. Scanner boundary: self-hosted engine, approved corporate scanning service or approved managed
   service; dependency, supply-chain and egress review as applicable.
2. Coverage: direct operator uploads only or every untrusted document-ingress path.
3. Execution: synchronous reject or asynchronous isolated quarantine and promotion.
4. Failure/retention: fail-closed behavior, bounded retry, infected/error retention and authorized
   rescan/delete operations.
5. Type and resource policy: content-signature allowlist, claimed/detected mismatch behavior,
   maximum file/batch sizes, timeout and signature freshness.

Until this workstream is implemented, the existing MIME allowlist, size limits and parser hardening
remain defense in depth but are not a malware-scanning control. This deferred risk must stay visible
in production risk acceptance.

## Workstream C — Persistent conversation history

Phase 2.5 adds bounded client-supplied `messages`/input history to the OpenAI-compatible adapters but
does not persist server-side transcripts. Phase 3 may add persistent conversations only after
deciding:

1. Conversation/thread ownership: consumer, authenticated end user, service identity or an explicit
   combination; never infer ownership from a caller-provided tenant/user field.
2. Object/action/field authorization for create, append, read, list, export and delete, including
   Personal MCP effective-actor semantics where applicable.
3. Data classification, encryption, regional storage, retention/expiry, legal hold, user deletion
   and provider-retention boundaries.
4. Prompt-injection/content safety, maximum turns/tokens/attachments, summarization lineage and
   whether summaries may outlive source messages.
5. Redacted audit/telemetry, tenant RLS, idempotent append, concurrency ordering and purge evidence.

No persistent transcript or “memory” claim is allowed before these controls are implemented and
verified. Client-supplied history remains available without creating server-side conversation
state.

## Workstream D — Optional bounded multi-agent supervision

Start this workstream only if Phase 2.6 sub-workflow and single-agent observe–act–verify composition
cannot satisfy a reviewed business scenario. Multi-agent is not a default architecture goal.

Decisions required before implementation:

1. Supervisor and specialist roles must be immutable and release-pinned; models cannot create or
   discover new agent authority at runtime.
2. Every specialist receives attenuated input, capability, tool, token, time and state budgets.
3. Delegation depth, fan-out, cycles, cancellation and cumulative budget ownership must fail closed.
4. Shared evidence needs typed merge/conflict semantics; ambient shared mutable memory is excluded.
5. Conflicting recommendations and every side-effecting final action require an explicit policy or
   human escalation contract.
6. Parent/child audit lineage must identify the initiating actor, effective authority, proposal,
   authorization decision, outcome and safe reason without persisting chain of thought.

Before implementation, require a separate ADR and threat model proving unique value beyond bounded
parallel/sub-workflow composition.

## Workstream E — Superadmin recovery authentication hardening

Add phishing-resistant MFA to the separate, non-daily Django superadmin recovery identity. Until
this workstream is implemented, Phase 2.8 Part 2.1 uses a unique strong password with guarded
custody, rotation, high-severity audit, immediate security/operator alerting and a recovery
runbook. This deferral is an explicitly accepted initial-stage risk, not evidence that a password
alone is equivalent to MFA.

Before implementation, select the authentication mechanism and recovery factors, define
enrolment/reset and credential-custody procedures, test lockout and recovery failure modes, and
update the superadmin threat model and operational runbook.

## Workstream F — Governed retrieval metadata

Implement the `metadata_filter` field reserved by the retrieval-profile contract. This work moved
from Phase 2.8 Part 5 to Phase 3 by owner decision on 2026-07-28. Until this workstream is delivered,
the field is validated as a bounded governed expression but is a documented no-op; it must not be
presented as narrowing retrieval results or as an authorization control.

Before implementation, define the authoritative metadata schema and ingestion lineage, field
allowlist and types, immutable document/chunk projection, PostgreSQL indexing strategy, migration
and backfill policy, and identical enforcement across keyword, vector, hybrid and hierarchical
summary-routing stages. Metadata may only narrow an already server-authorized tenant/grant/pinned
set-version/active-index corpus. Client-supplied organization, owner, role, permission or other
authority fields remain forbidden.

## Required planning artifacts

Before either workstream is implemented, create its dedicated task plan and proportionate threat
model. Personal MCP additionally requires an identity/data-flow diagram, ADRs for
IdP/OBO/downstream trust and a compatibility/rollout/rollback plan. Upload scanning requires an
upload/quarantine data-flow, scanner decision record, rollout/rollback plan and negative test matrix.
Persistent history requires a conversation ownership/data lifecycle ADR, privacy review, RLS and
authorization matrix, retention/purge runbook and migration/rollback plan.
Superadmin MFA requires an authentication design review, recovery-factor custody policy, negative
authentication tests and rollout/rollback evidence.
Governed retrieval metadata requires a field-schema decision, ingestion/backfill plan, query/index
design, cross-mode parity tests and cross-tenant/authority-negative tests.

## Status

Discovery/planned; no implementation approval or completion date assigned.
