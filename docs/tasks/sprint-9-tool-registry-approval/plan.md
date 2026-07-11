# Task Plan: sprint-9-tool-registry-approval

## Task summary

Add a tenant-scoped, release-pinned tool registry and execution proxy with explicit
risk policy, human approval, durable resume, schema validation, and redacted audit.

## Background

Sprint 8 provides bounded workflow execution but intentionally no arbitrary external
actions. Sprint 9 creates the only approved MCP/HTTP egress path. Planning may proceed
now; implementation requires the final workflow run/checkpoint contract and Sprint 7
network/telemetry conventions.

## Scope

- Immutable `ToolDefinition` and scenario-specific `ToolBinding` artifacts/models.
- Protocol, destination, contract, secret reference, risk, side-effect, timeout, rate,
  redaction, and approval policies compiled into releases.
- A Tool Execution Proxy with MCP and bounded HTTP adapters.
- `ApprovalRequest` lifecycle, authorized console/API decisions, expiry/cancel, and
  idempotent resume pinned to the same release/checkpoint/tool request.
- Tool/approval audit, trace, metrics, safe errors, and operational views.

## Non-goals

Unregistered URLs, caller-provided credentials/endpoints, arbitrary headers, direct
node network access, automatic approval of high-risk side effects, distributed
transactions/guaranteed external rollback, critical-risk tools by default, or agent
planning (Sprint 10).

## Acceptance criteria

- Only an active release-pinned binding can invoke an allowlisted tool/destination.
- ExecutionContext capability, tenant/scenario binding, contracts, field allowlist,
  risk, rate, timeout, and approval policy are enforced server-side.
- High-risk/side-effecting tools cannot execute before a valid authorized approval.
- Approval/rejection/expiry/cancel and retries cannot execute the same logical side
  effect more than once when the provider supports idempotency; uncertain outcomes
  are explicit and never reported as success.
- Tool output is treated as untrusted data, schema/policy validated, redacted, bounded,
  and never interpreted as system instructions.
- Resume uses the original immutable release, checkpoint, tool request checksum, and
  authorization context; every decision and outcome is audited safely.

## Affected components

New tools/approval services and models; artifacts, releases, workflows, gateway/MCP,
console, Celery, secret resolution, audit, observability, migrations, deployment
network policy, tests, and docs.

## Interfaces affected

Tool/ToolBinding artifact schemas; internal proxy adapter contract; approval list,
detail, decide, cancel, and status interfaces; MCP approval operation; workflow node
result waiting/resume states. Public changes require explicit contract approval.

## Data impact

Add tool definitions/bindings, approval requests/decisions, invocation attempts, and
idempotency/outcome records. Persist redacted summaries and checksums, never resolved
secrets or unrestricted tool inputs/outputs. Define retention and purge behavior.

## Security impact

This sprint creates intentional outbound access and side effects. SSRF, credential
exposure, confused deputy, prompt injection, replay, duplicate execution, approval
forgery, response poisoning, and data exfiltration are primary threats.

## Authorization impact

Tool administration and binding require scoped operator roles; approval requires a
role allowed by the pinned binding and separation-of-duties policy. Requester cannot
approve where self-approval is forbidden. Runtime checks consumer capability and
release binding again at execution/resume.

## Observability impact

Audit request, allow/deny, approval decision, attempt, outcome, timeout, cancellation,
and uncertain side effect with stable IDs/reasons. Metrics use bounded tool/risk/status
labels. Logs/traces exclude secrets and raw payloads.

## Migration impact

Additive tables, constraints, and indexes. Approval/run state additions must be
backward compatible across rolling deploys. No destructive migration.

## Dependencies

Verified Sprint 8 checkpoint/resume facade, Sprint 7 egress/telemetry controls, an
approved secret resolver, endpoint inventory, approver roles, and provider idempotency
contracts. Any MCP/HTTP client or secret-manager dependency needs explicit approval.

## Implementation steps

1. Define schemas, models, constraints, roles, risk policy, and migrations.
2. Extend release compilation with immutable definitions/bindings and destination pins.
3. Implement central policy/proxy flow and bounded MCP/HTTP adapters.
4. Integrate secret resolution with least privilege and zero-value persistence/logging.
5. Add transactional approval lifecycle, expiry/cancel, idempotent resume, and uncertain
   outcome handling.
6. Add scoped console/API/MCP views, audit, metrics, alerts, and runbooks.
7. Add contract, SSRF, authorization, concurrency, failure, and end-to-end tests;
   update current-state documentation after verification.

## Test plan

- Schema/risk/side-effect/default-deny and release-pin tests.
- Unregistered/private/redirected/DNS-rebound destination, header, method, size,
  timeout, TLS, and content-type tests.
- Cross-tenant tool/binding/approval and unauthorized/self/stale approval denial.
- Secret redaction and least-privilege resolver failure tests.
- Input/output schema, prompt-injection content, malformed MCP/HTTP, and truncation tests.
- Concurrent decisions, worker redelivery, idempotency, timeout-after-send, cancel, expiry,
  and uncertain external outcome tests.
- Approval → resume → completion/rejection end-to-end with audit and network policy.

## Rollout plan

Apply migrations and deploy registry/proxy disabled. Register read-only low-risk tools
in a test tenant, validate egress/audit, then enable medium/high-risk bindings with
named approvers and runbooks. Critical tools remain disabled absent separate approval.

## Rollback plan

Disable all tool execution and new approvals centrally; preserve pending requests and
explicitly cancel/expire them without external calls. Resume workflows through defined
fallback where contracts permit. Retain additive records/audit for investigation.

## Risks

- External side effects may succeed despite a local timeout or crash.
- DNS/redirect behavior can bypass naïve allowlists.
- Approvers may lack enough safe context or become a high-value compromise target.
- Tool output can carry prompt injection or sensitive data.

## Open questions

- Network enforcement owner and the initial approved endpoint inventory.
- Selected corporate secret-manager provider, External Secrets Operator availability,
  rotation interval, and emergency credential-revocation owner.
- Approval delegation and emergency-access procedure.
- Data classification, redaction, and retention per tool.

## Approved decisions

- Only platform-admin-registered HTTPS/MCP destinations may be invoked. Caller-provided
  URLs, private/link-local/metadata destinations, uncontrolled redirects, and
  destinations outside the approved inventory are prohibited.
- The preferred production model is a corporate external secret manager integrated
  through the Red Hat OpenShift External Secrets Operator. AgentHub stores only a
  logical `secret:<name>` reference and never stores a third party's token in its
  database, artifacts, logs, audit records, or operator-visible configuration.
- Native OpenShift Secrets are a temporary fallback only when an external manager is
  unavailable. That fallback requires encryption at rest, least-privilege RBAC,
  restricted human `get`/`list` access, an approved non-plaintext provisioning path,
  rotation ownership, and a recorded migration plan to external secret management.
  Plaintext manifests, shell-history exposure, and handing credentials to AgentHub
  application administrators are prohibited.
- Only side-effecting `high`-risk invocations require human approval in the initial
  release. The requester cannot approve their own high-risk request. `critical` tools
  are disabled.
- Approval expires after 30 minutes and is bound to the exact tool request checksum.
  Any material input, binding, release, or policy change requires a new approval.
- Side-effecting providers must use idempotency keys when supported. A timeout or lost
  response after dispatch without a provable provider result becomes `outcome_unknown`
  and is not retried automatically.
- These decisions were approved by the project owner on 2026-07-10.

## Status

In progress, delivered as verified, independently committable increments.

- Increment A — **implemented and verified** (SQLite + PostgreSQL): `tool_definition`
  / `tool_binding` artifact validation (bounded, allowlisted, https-only, IP/private
  hosts rejected, `critical` disabled, `secret:<name>`-only credentials), the
  tenant-scoped immutable `ToolDefinition` / `ToolBinding` registry models with a
  status-only mutation path, registration services enforcing the high-risk
  side-effecting approval invariant, and fail-closed release pinning of active,
  checksum-matched bindings. No execution proxy, egress, secret resolution, or approval
  lifecycle yet — the platform performs no tool egress. See `verification.md`.
- Increment B — **implemented and verified** (SQLite + PostgreSQL): the central
  default-deny `invoke_tool` proxy (capability, contracts, field allowlists, risk),
  SSRF-safe destination validation (public-unicast-only, DNS-rebinding defense via
  resolved-IP checks), the transport-adapter and least-privilege secret-resolver seams,
  and `resolve_release_tool`. The default adapter performs no network I/O and the proxy
  has no production caller yet — there is still no live tool egress. See
  `verification.md`.
- Increment C — **implemented and verified** (SQLite + PostgreSQL): additive
  `ToolInvocation` / `ApprovalRequest` models and the `request_tool_invocation` /
  `decide_approval` / `execute_invocation` / `cancel_invocation` services —
  separation-of-duties, request-checksum binding (input-swap defense), 30-minute
  approval expiry, idempotent resume that never double-executes, uncertain-outcome
  handling, and redacted fail-closed audit. Still no live egress and no public caller.
  See `verification.md`.
- Increment D — **planned**: the real HTTP/MCP adapter and its network dependency
  (requires explicit approval); wiring the proxy/approval flow into a workflow `tool`
  node with pause/resume; and console/API/MCP approval surfaces plus metrics. These
  require explicit approval for authorization, public API, secret, dependency, and
  network changes before landing.

## Completion criteria

Definition of Done evidence covers default-deny authorization, tenant isolation,
SSRF/egress, secrets/redaction, schemas, approval/resume concurrency and idempotency,
uncertain outcomes, migrations, audit, operability, and manual security review.
