# Threat Model: phase-2-6-part-11-product-operational-closure

Proportional model: this part adds read/presentation surfaces, eval vocabulary, telemetry and a
deliberate destructive purge capability — no new execution authority, grammar or egress. The
dominant risks are over-disclosure, cross-tenant reads, unsafe deletion and publishing
non-synthetic data.

## Assets

- Tenant run evidence: branch/wait/retry/compensation/child/agent trails (confidential metadata,
  integrity-relevant for audit and eval).
- Audit records and eval reports (integrity, retention, tamper evidence).
- Published GitOps scenario pack (public-in-repo; must be fully synthetic).
- Operator dashboards/alerts (availability of incident response).
- Retention windows and purge authority (destructive capability).

## Actors

- Tenant members with console/Studio roles (authorized readers, bounded by membership/role).
- Platform operators (retention, alerts, acceptance actions).
- Hostile cross-tenant or role-escalating users probing new read endpoints.
- Repository readers of published GitOps examples (untrusted world once committed).

## Entry points

- New/extended console/builder JSON read surfaces (session/LDAP + CSRF, tenant-scoped).
- Eval suite artifacts (data-only assertions) and eval report views.
- Retention/purge management commands and scheduled jobs.
- Monitoring endpoints (existing bearer-token metrics; new series only).
- Demo-seed reset procedure (separately confirmed operational action).

## Trust boundaries

- Server-rendered redacted evidence ↔ browser SPA: the client is non-authoritative and receives
  only role-filtered, redacted metadata.
- Eval assertions ↔ run evidence: closed data vocabulary, no code execution, isolated candidate
  seam unchanged.
- Purge jobs ↔ durable evidence: policy windows and fail-closed guards stand between a scheduler
  and irreversible deletion.
- Repository ↔ GitOps examples: compiler-validated synthetic fixtures only, after owner review.

## Data classifications

- Trace/eval renderings: internal, tenant-confidential metadata (codes, checksums, counts,
  timestamps) — payloads, prompts, arguments, secrets and endpoints are excluded.
- Metrics: aggregate, bounded labels, no identifiers.
- GitOps pack: public synthetic data.
- Purge audit: restricted, durable, non-deletable by the purge itself.

## Authentication

Unchanged (console session/LDAP + CSRF; metrics bearer token; no new anonymous surface).

## Authorization

Deny by default on every new read/action: membership-scoped organization reads, role-gated
mutations (retention actions platform-operator scoped), server-side enforcement, negative tests
required. Eval/promotion/release authority unchanged.

## Tenant isolation

All rendered evidence queries are organization-bound with existing tenant scope/FORCE RLS
mechanisms and PostgreSQL non-owner coverage; cross-tenant trace/eval/retention access is a
required denial test, not an assumption.

## External systems

None added. No live egress; deterministic providers for the acceptance pack; live monitoring
infrastructure remains a recorded follow-up.

## Abuse cases

- Authorized-but-curious user harvesting another tenant's run structure via trace/eval endpoints
  (IDOR, locator guessing).
- Redaction gap shipping payload/prompt/secret content into traces, eval reasons, alerts or
  metric labels.
- Purge abuse or misconfiguration deleting in-window evidence or audit trails; purge replay
  amplifying deletion.
- Crafted eval suite probing for unredacted failure output or unbounded assertion input.
- Real tenant data or credentials smuggled into the published GitOps pack or journey recordings.
- UI exposure making a deployment-gated capability (Python execution, live MCP) reachable.
- Alert flooding/cardinality explosion degrading monitoring during an incident.

## Failure cases

- Purge job crash mid-batch: bounded batches + idempotent audited re-run; ambiguity fails closed.
- Reset procedure targeting a wrong database: fails closed on the explicit-name check (P2.6.0
  procedure).
- Recovery drills intentionally kill workers: must converge without duplicate side effects.
- Audit persistence failure during a retention action: fail closed (action denied).

## Logging and audit risks

- New read surfaces must not log rendered evidence bodies; access to sensitive views is auditable
  per existing console patterns.
- Purge must audit what class/window/count was deleted (safe metadata), never row contents.
- Journey recordings/screenshots must contain synthetic data only.

## Mitigations

- Server-side role/tenant filtering with negative tests per new endpoint; opaque public locators.
- Single redaction seam for evidence rendering, asserted by tests (codes/checksums/counts only).
- Closed assertion vocabulary, bounded assertion inputs, redacted stable reason codes.
- Purge: owner-approved windows, report-mode default, bounded audited batches, audit/in-window
  exclusion lists, fail-closed ambiguity, idempotent re-run.
- GitOps pack built exclusively from synthetic fixtures, compiler-validated, owner-reviewed before
  commit; secret scan over the pack.
- Gated capabilities rendered as status, never as executable actions; server re-checks gates on
  every action regardless of UI state.
- Bounded metric label sets and reviewed alert thresholds.

## Residual risks

- Metadata-level traces still reveal process shape (node names, counts, timing) to authorized
  tenant members; accepted as intended product function.
- Live alert/dashboard behavior is unverified until the operational follow-up runs against real
  monitoring infrastructure.
- Purge correctness for future data classes depends on parts registering them; an unregistered
  class ages without retention until added (documented gap, monitored).

## Required security tests

- Cross-tenant and role-denial matrix over every new trace/eval/retention surface (SQLite +
  PostgreSQL non-owner/RLS).
- Redaction assertions for traces, eval reports, alerts, purge audits and metric labels.
- Purge window/audit-preservation/report-mode/idempotency/fail-closed tests.
- Gated-capability negative tests: UI exposure paths cannot trigger gated execution server-side.
- Secret/PII scan of the GitOps pack and journey evidence.
- Recovery drills asserting no duplicate side effects and complete audit trails.
