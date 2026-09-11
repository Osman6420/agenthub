# Threat Model: P2.6.3 Durable Waits

## Assets and trust boundaries

- Assets: tenant workflow state, immutable release/compiler lineage, pending-action checksum,
  decision authority, opaque event correlation, resume payload and audit evidence.
- Untrusted inputs: HTTP credentials and bodies, correlation IDs, human decisions, event payloads,
  Celery redelivery and stale scheduler messages.
- Trust boundaries: public gateway authentication, console user authentication and organization
  membership, PostgreSQL tenant rows/transactions, Celery delivery, and P2.6.1 state mapping.
- PostgreSQL is authority; Redis/Celery conveys hints only. Audit for resume/decision transitions is
  required and transactionally coupled.

## Threats and controls

| Threat | Control | Required evidence |
| --- | --- | --- |
| Forged/stolen correlation | opaque UUID, hash lookup, owner-scoped disclosure and authenticated exact-consumer ownership | forged-ID and wrong-consumer tests |
| Replay/duplicate delivery | row lock, pending-only transition, consumed timestamp, stable replay denial | sequential and concurrent replay tests |
| Cross-tenant confused deputy | organization lineage on every row/query; tenant context; no body tenant | cross-tenant tests |
| Actor/role spoofing | actor and roles resolved from authenticated user membership; body has no authority fields | wrong-role and unexpected-field tests |
| Self approval | requester subject stored server-side; configurable deny-self invariant | separation-of-duties test |
| Payload mass assignment | exact request envelope and JSON Schema with bounded size; P2.6.1 protected destinations | schema/protected-field tests |
| Pending action substitution | server-generated checksum binds run, node, workflow/release/checksum and config | checksum/wrong-state tests |
| Expired/stale resume | database deadline checked under lock; exact compiler contract required | expiry and stale-version tests |
| Cancel/timeout race | same locked run/wait transaction; terminal run wins and cannot be resurrected | race/interleaving tests |
| Worker sleep/exhaustion | deadline persisted; bounded periodic reconciler only | timer/recovery tests |
| Identifier/payload leakage | correlation appears only in owner-scoped status and never logs/audit; payload audit uses sizes/checksums only | audit redaction test |
| Audit bypass | required audit write in transition transaction; failure rolls transition back | audit-failure test |

## Data classification and retention

Correlation is a non-authorizing opaque public identifier; its lookup hash and immutable lineage
are security metadata, and it is excluded from logs/audit. Human/event payloads may contain confidential business data: only schema-
validated, redacted workflow state is retained; audit stores identifiers, outcome and reason codes.
Retention/purge policy is integration-owned P2.6.11 work; until then records follow workflow-run
retention and are protected from independent deletion.

## Residual risks

- Existing consumer bearer authentication is the event-producer identity; OIDC/mTLS and delegated
  producer identities remain later hardening.
- Scheduler cadence can delay a deadline but cannot execute it early or lose it.
- Full PostgreSQL RLS coverage depends on the repository-wide non-owner application-role rollout.
