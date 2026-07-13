# AgentHub — Security & Safety: How and Why It Is Secure

A technical presentation of AgentHub's security architecture: the trust model, the
defense-in-depth controls, and the design principles that make an AI platform — including
tool use and autonomous agents — safe to operate for multiple tenants.

> **One-sentence thesis.** AgentHub treats every input, model decision, and frontend as
> **untrusted**; every action is **denied by default** and re-authorized **server-side**
> against **immutable, checksummed** release state, and everything of consequence is
> **audited** and **fails closed**.

---

## 1. Security posture at a glance

| Principle | How AgentHub applies it |
| --- | --- |
| **Deny by default** | No object, action, tenant, or field is accessible unless an explicit server-side check allows it |
| **Server-side authority** | Client roles, tenants, owners, and "the model said so" are never trusted; the backend re-decides everything |
| **Tenant isolation** | Every query is bound to the authenticated organization/consumer via authoritative columns, not client input |
| **Immutability + pinning** | Definitions are checksummed artifacts; a release pins exact versions; a running scenario cannot silently change |
| **Least privilege** | Consumers, operators, workers, tools, and secrets each get only what they need |
| **Fail closed** | Ambiguity, timeout, or partial success becomes a safe deterministic failure, never a silent pass |
| **Defense in depth** | Independent layers (auth, schema, tenancy, egress, approval, contract, audit) each re-check |
| **Auditable** | Security-sensitive state changes produce a separate, redacted, append-only audit trail |

---

## 2. Trust model

**Assets.** Tenant data and documents, model/tool budgets, artifacts/releases, execution
context, checkpoints, tool authority, approvals, external side effects, and audit
integrity.

**Actors.** Consumers (API callers), tenant operators (by role), platform operators,
workers, model/retrieval/tool providers — and adversaries: malicious users, poisoned
content, and a compromised/novel model.

**Trust boundaries (everything crossing a boundary is re-validated):**

```
  consumer input ─▶ gateway            (authN + authZ + schema + rate limit + idempotency)
  operator input ─▶ console/builder    (LDAP/session + role + tenant scope + CSRF)
  retrieved/tool content ─▶ model      (treated as tainted; never trusted as instructions)
  model decision ─▶ runtime guards     (re-validated against the immutable allowlist)
  queue message ─▶ worker              (claims + re-resolves authoritative state)
  tool attempt ─▶ egress               (capability + risk + approval + SSRF checks)
  any output ─▶ policy/contract        (validated before it reaches a consumer)
```

The critical inversion: **a model's tool selection is a *proposal*, not an authorization.**
The runtime re-checks capability, release binding, risk, and approval every time.

---

## 3. Identity and authentication — two separated planes

AgentHub deliberately keeps the **public data plane** and the **operator control plane**
on different identities and paths:

| Plane | Who | AuthN | Surface |
| --- | --- | --- | --- |
| **Data plane** | Consumers (machines) | **Bearer token**, stored **hashed** (`ConsumerToken`) | `/v1/*`, MCP |
| **Control plane** | Operators (people) | **LDAP / directory** session (ADR-0001) | `/console/*`, builder API |

Consequences:
- A leaked console session cannot call the consumer API as a tenant, and a consumer token
  cannot reach an operator surface.
- The visual builder is **not** a new identity system: it reuses the console session and
  the Sprint 1 role/tenant model, is **same-origin** (no CORS), and enforces **CSRF** on
  every mutating call. Unauthenticated calls get `401`; unauthorized get `403`.
- Django Admin is removed as a management surface (local-dev opt-in only).

Workers use their own workload identity and **re-resolve authoritative state** from the
database rather than trusting the queue message. Serialized state (checkpoints) never
carries a tenant selector and can never *grant* a permission.

---

## 4. Authorization — deny by default, four dimensions

Every protected operation is checked server-side along **object, action, tenant, and
field**:

- **Read scope** is membership-based: `allowed_organization_ids(user)` is the single source
  of truth for "which organizations may this user see," so a forgotten filter in one view
  cannot widen visibility.
- **Write gates** are role-based in the *target* organization: e.g. authoring requires
  `can_author_scenarios`; releases require `can_manage_releases`. Platform admin (superuser)
  may cross org boundaries.
- **Field-level** exposure is curated: responses project only safe fields (for example the
  builder's node-schema returns tool binding **role names**, never endpoints or secrets).

Negative authorization is a first-class test requirement: cross-tenant, wrong-role,
unauthenticated, and privilege-escalation cases are explicitly tested to be **denied**.

---

## 5. Tenant isolation

Multi-tenancy is enforced by **authoritative columns**, not by anything the client can set:

- Every tenant-scoped queryset filters on the verified `organization` / `consumer` id.
- A draft, run, release, checkpoint, index, tool binding, approval, or eval outside the
  caller's scope is **not found** (no existence disclosure) or denied.
- Publishing writes into the artifact's *own* organization only; the tenant cannot be
  spoofed from request input.
- Cross-tenant access is a standing negative-test class across the gateway, console,
  builder, tools, and agents.

---

## 6. Immutability and release integrity

Nothing a consumer touches is mutable at runtime:

- **Artifacts** (`ArtifactVersion`) are immutable, versioned, and **SHA-256 checksummed**
  over canonical JSON. Tool definitions/bindings and compiled agents are write-once.
- A **release** compiles a manifest that **pins exact artifact versions (and indexes and
  tool bindings) by role**, with a single-active invariant enforced in the database.
- **Fail-closed promotion**: a release is promoted only with a **passing eval bound to the
  pinned suite checksum** and ready, tenant-owned pinned indexes. Rollback atomically
  restores the superseded release.
- A running scenario is pinned to its release, versions, execution context, limits, and
  checkpoint **across retries and approval resume** — there is no silent upgrade mid-run.

This is why "the model got confused by a swapped tool" or "someone changed the prompt under
a live run" are not reachable states.

---

## 7. Input and output security

- **Explicit schemas and allowlists.** Artifact bodies are validated per type; contracts
  are validated as JSON Schema; the workflow DSL is compiled by a strict, deterministic
  compiler that allowlists node types, rejects unknown/dangerous keys, bounds node/edge
  counts, and forbids cycles. Consumer input is validated against the release input
  contract.
- **Injection / traversal / deserialization.** Parameterized queries, no code execution
  from the DSL (condition expressions are parsed against a bounded, forbidden-operation
  allowlist), and no unsafe deserialization of untrusted content.
- **Output governance.** Model output must pass the output contract and policy before it
  reaches a consumer; invalid output triggers a safe fallback, never a raw passthrough.
  Grounding thresholds and runtime-generated citations back RAG answers.

---

## 8. Governed egress and the tool proxy (SSRF-safe)

All outbound tool calls flow through one central, default-deny proxy — there is no side
channel:

- **Capability, contract, and field allowlists** are enforced (mass-assignment and
  exfiltration defense).
- **SSRF-safe egress**: destinations are **HTTPS-only, public-unicast-only**; private,
  loopback, link-local, metadata, `.internal`, and `localhost` targets are rejected, and
  the check is performed against the **resolved IP** to defeat **DNS rebinding**.
- **Bounded**: outbound calls have connection/read timeouts and capped response sizes.
- **Least-privilege secrets**: credentials appear only as `secret:<name>` **references**,
  resolved at call time — never embedded, logged, or returned.
- **Default adapter opens no socket**: the platform's default tool adapter is deterministic
  and performs **no live egress**; real HTTPS/MCP egress is opt-in and project-owner
  approved.
- **Model, embedding and OCR destinations are platform profiles**: tenant/request content cannot
  choose host, path, credential or TLS behavior. OCR service-returned status/result URLs are ignored;
  only catalog-derived paths are used. Non-idempotent OCR submit is never blindly retried, and ACK
  occurs only after checksumed tenant-object-store persistence.

### Human approval with separation of duties

High-risk, side-effecting tools require a durable approval:

- A **request-checksum binding** prevents swapping the input after approval.
- **Separation of duties**: the approver must differ from the requester.
- **30-minute expiry**, **idempotent resume that never double-executes**, and an
  **`outcome_unknown`** state for a dispatched-but-unconfirmed call that is **never retried**
  (no duplicated side effects).

---

## 9. Agent runtime safety

Autonomous agents are the highest-risk workload, so they run inside hard rails:

- **Bounded loops**: step, tool-call, token, wall-clock deadline, state-size, and
  checkpoint-schema-version caps each terminate deterministically with a stable code and
  **no uncontrolled requeue** (denial-of-wallet / runaway-loop defense).
- **Untrusted-planner defense**: *every* planner decision is re-validated against the
  immutable **compiled tool allowlist** and a decision-kind allowlist — a compromised or
  novel planner cannot widen the tool surface or skip approval.
- **Tool use only through the proxy/approval boundary** above, with a per-step idempotency
  key.
- **Framework confinement**: LangGraph is integrated **only** as a planner adapter behind a
  flag (default off); it owns planning transitions but **cannot reach** durable state,
  tenant isolation, the tool boundary, approval, audit, or idempotency. No hosted
  LangGraph/LangSmith service and no new public endpoint were added.
- **Redacted trajectories**: raw chain-of-thought and raw payloads are never persisted;
  only allowlisted decision/outcome labels, counters, and checksums are stored, and the
  operator trace view is tenant-scoped.

---

## 10. The visual builder's security model (Sprint 11)

The builder adds a rich UI **without** adding attack surface, by keeping the frontend
non-authoritative:

- **The DSL and backend API are the source of truth.** The React Flow client holds **no**
  authoritative validation, authorization, lifecycle, promotion, or execution logic. Every
  save, validate, and publish is a backend round-trip.
- **One publish path.** Publishing routes through the same `create_artifact_version` used by
  GitOps — same schema validation, same inline-secret rejection, same checksum. A crafted
  graph cannot bypass a control the platform already enforces.
- **No secret/endpoint disclosure.** The node-schema endpoint returns only builtin node
  types, org-allowlisted custom-node refs, and tool binding **role names + approval flag** —
  never tool endpoints, tool-definition manifests, or `secret:<name>` values.
- **Reused identity, same-origin, CSRF.** Session/LDAP auth, membership read scope,
  `can_author_scenarios` write gate, CSRF on mutations, `401/403` JSON, no CORS. Read-only
  mode in the UI merely mirrors the server's `can_write` decision; the server still
  re-checks every write.
- **Supply chain contained**: the SPA is a build-time-only dependency set with a **pinned
  lockfile**; CI runs `npm ci` (fails closed on lockfile drift) → typecheck → tests → build.
  No new Python runtime dependency; the built bundle is served same-origin as static assets.

---

## 11. Secrets and data protection

- Secrets are **forbidden in source, tests, artifacts, logs, and examples**; an inline-secret
  scanner rejects any artifact body carrying a literal secret, allowing only
  `secret:<name>` references resolved through an approved mechanism.
- Telemetry and errors are **redacted**: tokens, cookies, authorization headers, keys, raw
  payloads, document contents, and model prompts/responses with protected data are never
  logged.
- Data minimization: only policy-approved redacted state plus checksums and opaque
  identifiers are persisted (e.g. agent run ids are opaque UUIDs).

---

## 12. Observability and audit

- **Application logs** are structured, carry propagated request/trace ids and safe
  actor/tenant references, and use bounded field names/values.
- **Security/business audit is separate** from debug logging: an append-only trail records
  actor, effective identity, tenant, action, target, authorization decision, outcome,
  reason code, and trace — for authoring, publishing, promotion, approvals, and
  administrative actions. Builder draft create/update/delete/publish are audited (publish
  records the artifact checksum).
- **Metrics/traces** keep identifiers, prompts, URLs, and tenant values **out of labels** to
  control cardinality and protect privacy.

---

## 13. Fail-closed behaviors (selected)

| Situation | Result |
| --- | --- |
| Missing/invalid authN or authZ | Deny (`401` / `403`), audited |
| Cross-tenant reference | Not found / denied — no existence disclosure |
| Invalid artifact/DSL or inline secret on publish | Rejected; nothing persisted |
| Promotion without a passing bound eval / ready index | Refused |
| Tool destination private/loopback/rebound IP | Egress blocked |
| Approval rejected or expired | Run fails closed; no side effect |
| Dispatched tool call with lost response | `outcome_unknown`; never retried |
| Agent hits a step/token/time/state cap | Deterministic terminal error + audit |
| Model proposes an unbound tool | Rejected by the runtime allowlist |
| Invalid model output | Safe fallback, not raw passthrough |

---

## 14. Residual risks and honest limits

- **Prompt injection is not "solved."** Models remain vulnerable to novel injection; the
  design assumes this and confines the blast radius (proposals re-validated, tools gated,
  output governed, budgets bounded) rather than trusting the model.
- **Exactly-once external effects** depend partly on providers; AgentHub guarantees no
  *double* execution and records uncertain outcomes, but a provider that acted before losing
  the response leaves an unavoidable uncertain window (handled as `outcome_unknown`).
- **In-process framework/library defects** (e.g. LangGraph) could affect tenants; it is
  confined to the planning seam and off by default.
- **Operational follow-ups not yet implemented**: a global agent start/resume kill switch,
  automated checkpoint retention/purge, and production-like load / denial-of-wallet tests.
- **Not yet in place**: live-approved LLM endpoints/credentials and real embedding providers.
  Phase 2 P1 provides an opt-in real chat provider behind a platform-managed, immutable profile
  catalog and SSRF-safe pinned-IP transport; deterministic remains the default and CI makes no
  live call,
  live production deployment (Sprint 7 manifests are reviewed drafts), and OIDC/JWT/mTLS
  consumer auth (bearer-token today); LDAP is configured but not yet validated against a
  live directory.

Nothing above is a silent gap — each is tracked in the planning and threat-model records.

---

## 15. Where to verify this in the code

| Control | Location |
| --- | --- |
| Tenant read scope | `apps/tenancy/services.py` (`allowed_organization_ids`) |
| Role write gates | `apps/tenancy/services.py` (`can_author_scenarios`, `can_manage_releases`) |
| Artifact validation + inline-secret scan | `apps/artifacts/validation.py`, `apps/artifacts/secrets.py` |
| Workflow compiler (allowlists, no cycles) | `apps/workflows/compiler.py` |
| Fail-closed release lifecycle | `apps/releases/lifecycle.py`, `apps/releases/compiler.py` |
| Gateway authN/authZ/rate-limit/idempotency | `apps/gateway/` |
| SSRF-safe egress + tool proxy | `apps/tools/egress.py`, `apps/tools/proxy.py` |
| Approval lifecycle (separation of duties, expiry, resume) | `apps/tools/approvals.py` |
| Agent guards + planner revalidation | `apps/agents/` |
| Builder (non-authoritative API, role-only schema) | `apps/builder/` |
| Audit trail | `apps/audit/` |
| Security rules (the standard) | `docs/ai/security-rules.md` |

Verification evidence for each increment lives in `docs/tasks/<sprint>/verification.md`.
