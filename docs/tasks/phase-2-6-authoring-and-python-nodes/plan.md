# Task Plan: phase-2-6-authoring-and-python-nodes

## Task summary

Plan two related but independently deliverable Phase 2.6 capabilities:

1. scenario-author Python-node drafts that become executable only after exact-revision platform
   review and activation, and only in an approved isolated runner; and
2. a tenant-aware AI workflow planner embedded directly in Scenario Studio, producing transient
   graph/JSON candidates from server-owned capability context without requiring user-supplied system
   identifiers.

This record plans implementation only. It does not authorize tenant-code execution, a runner or
production dependency, authentication/authorization changes, live model egress, database reset or
production activation.

## Background

The current platform has useful seams but does not implement the requested behavior:

- `CustomNodeDefinition` represents platform-preinstalled package executors. `execute_custom_node`
  resolves an in-process registered callable and therefore cannot safely run tenant code.
- Workflow custom-node config is a fixed `node_ref` plus generic `fields`; dynamic public config
  schemas are not authoritatively applied by the compiler/Studio.
- AI authoring receives a static server prompt and user description only. It does not receive a
  bounded scenario capability snapshot.
- Candidate acceptance currently requests a name and logical ID and persists a `WorkflowDraft`
  through a separate acceptance step.
- `WorkflowDraft` already provides mutable author state, scenario lineage and revision-based
  optimistic concurrency. Publishing already routes through canonical artifact validation.
- `allocate_identifier` already provides collision-safe server identifiers but builder draft creation
  does not use it.

## Architecture decisions proposed for approval

### Two node execution classes

Do not rename or reinterpret the existing artifact/runtime contract. Preserve it as:

- **Managed node**: platform-preinstalled, exact-package-version executor; existing
  `custom_node_definition`, registry and releases remain compatible.
- **Python node**: scenario-author source with a separate draft/review/revision model and isolated
  execution boundary.

Both may appear under the workflow node family `custom`, but their catalog entry includes an
explicit `execution_class` (`managed` or `python`). New Python-node workflow config uses a fixed
envelope:

```json
{
  "node_ref": "number-multiply-abcd1234:r3",
  "parameters": {
    "factor": 2
  }
}
```

The fixed `parameters` object is preferred over mixing arbitrary user-defined keys beside
`node_ref`: it prevents reserved-key collisions and permits exact JSON Schema validation. Existing
managed-node `fields` config remains accepted for backward compatibility until a separate migration
decision.

### Source and public metadata separation

Python source is not an `ArtifactVersion` body, workflow JSON, release manifest or node-schema
payload. Store source as a bounded immutable content-addressed blob or protected field selected by
the isolation/storage ADR. Public catalog metadata carries only display name, purpose, opaque
`node_ref`, execution class, active revision/checksum and bounded config/input/output schema
summaries. Release compilation pins the exact active revision and checksum.

### Minimum isolation plus automated and human review

Admin review is necessary but cannot reliably detect every resource-exhaustion, unsafe-input or
runtime behavior. Automated review improves coverage but cannot prove arbitrary Python safe. The
first release therefore uses all three controls:

1. mandatory versioned automated security review;
2. exact-checksum platform-admin review; and
3. a separate credentials-free, network-denied, resource-limited runner.

AST filtering, restricted builtins, import hooks and Python subinterpreters are defense in depth,
not a complete runtime boundary. Before any source test or runtime implementation, run a focused
spike and approve an ADR covering:

- the minimum dedicated rootless/locked-down runner container/service with dropped capabilities,
  read-only root filesystem, network deny and no platform credentials;
- operational fit, cold start, cancellation, resource accounting, image/stdlib governance, patching,
  queue isolation and evidence collection; and
- whether stronger gVisor/Kata/microVM isolation materially reduces the measured risk enough to
  justify its operational cost. Stronger sandboxing is optional for the first release unless the
  spike or deployment policy requires it.

The runner receives only a one-time bounded execution request and returns a bounded JSON patch. It
has no application DB credential, object-store credential, secret-store access, service account
token, ambient network, host mount or process-launch capability. The runner API itself must be
authenticated, replay-safe and inaccessible to tenants directly.

### AI candidate is transient Studio state

Generation returns a bounded structured response to the existing Studio page. It does not create a
database draft. Initial delivery keeps candidate/model output in React memory only, with
`beforeunload` protection. Do not use browser persistent storage for workflow output or Python source
until a separate privacy/XSS decision.

The server supplies a temporary canonical `metadata.id` placeholder for diagnostics. On explicit
save it allocates the final logical ID, rewrites the authoritative body server-side, rechecks
lineage/authorization and reruns canonical validation.

## Scope

### P2.6.8A — Isolation spike and contracts

- Threat model the full author → review → test → activation → execution → disable dataflow.
- Select runner boundary through ADR and document development/production topology.
- Define runner request/response protocol, authentication, request checksum, idempotency,
  cancellation, timeout and `outcome_unknown` semantics.
- Define hard caps for source bytes, schema bytes/depth, input/output bytes, CPU/wall time, memory,
  PIDs, filesystem scratch and concurrent executions.
- Define a platform-owned standard-library module allowlist. Authors request only a subset; neither
  organization nor platform review can add modules absent from deployed runner policy.
- Define forbidden syntax/import/reflection/serialization behaviors as defense in depth.
- Define mandatory automated review executed on every submitted immutable revision:
  - Python parse/syntax and AST policy;
  - closed import/module allowlist;
  - forbidden `eval`, `exec`, `compile`, `open`, `__import__`, dunder/reflection, process, network,
    filesystem and unsafe serialization patterns;
  - bounded source/schema/depth checks and input/config/output schema fixtures;
  - approved static security rules (for example a pinned Bandit/Semgrep-equivalent ruleset if owner
    approves the dependency, otherwise repository-owned checks for the initial spike);
  - isolated timeout, CPU/memory/PID/output-limit probes; and
  - a content-free report bound to source/schema/module checksum and exact rule-set revision.
- Critical automated findings block review submission/approval and cannot be overridden. Warnings may
  be accepted only by platform admin with a bounded rationale tied to the exact report checksum.
- Decide source encryption/storage, authorized viewers, retention and deletion/disable behavior.
- No tenant source is executed during this part unless the spike environment is explicitly approved
  and contains no platform credentials or network authority.

### P2.6.8B — Python-node authoring and review control plane

Plan additive tenant-owned models with direct organization lineage:

- `PythonNodeDraft`: organization, project, scenario, display name, description, current mutable
  content, author/update identity and optimistic revision.
- `PythonNodeRevision`: immutable server-generated logical ID/revision, source checksum, config/input/
  output schema checksums, requested module set, source locator and creation lineage.
- `PythonNodeReview`: exact revision/checksum, reviewer, decision, bounded safe reason/change request,
  timestamps and decision history.
- `PythonNodeActivation`: exact approved revision/checksum, active/disabled state and actor/reason.
- `PythonNodeTestRun`: bounded synthetic test metadata/result code; source, raw input and output are
  not audit payloads and follow short retention.
- `PythonNodeSecurityReview`: immutable source/schema/module checksum, rule-set revision/checksum,
  safe finding codes/severities/counts, resource-probe summary and overall pass/block status; no
  source excerpt or raw scanner output.

Lifecycle:

```text
mutable draft
  -> immutable submitted revision
      -> changes_requested | rejected | approved
          -> active
              -> disabled
```

- Editing a submitted/decided revision creates a new immutable revision; it never mutates reviewed
  content.
- Review decision and activation require platform admin and bind exact checksums under transaction.
- Platform-admin review sees the exact automated report. Critical status prevents approval at the
  service/database boundary; warning acceptance records an explicit rationale.
- Approval and activation may be one explicit atomic platform-admin action or two explicit actions;
  choose in implementation plan, but no approved revision becomes active accidentally.
- Scenario authors may create/edit/test/submit only within `can_author_scenarios` scope.
- Organization admins may list/detail safe metadata and review status for their organization but do
  not approve or view source by default.
- Platform admins may view source, approve, request changes, reject, activate and disable.
- Auditors receive read-only safe metadata, checksum and review history; no source/test payload.
- Disabled organization rules and cross-tenant indistinguishable-not-found behavior remain.
- All IDs, logical IDs and revision numbers are server-generated through the canonical identifier
  allocator under collision constraints. Scenario/project/organization come from the authorized
  Studio route, never request-body authority.

### P2.6.8C — Compiler, release and runner integration

- Extend the safe node catalog with explicit managed/Python entries and public schemas.
- Canonical compiler resolves the exact `node_ref`, validates `parameters`, input state and output
  patch contracts, and rejects pending/rejected/disabled/foreign/stale-checksum revisions.
- Workflow publish may reference only active revisions. Mutable Studio may show unresolved pending
  capability, but the unresolved graph remains transient and cannot pass save/publish.
- Release compiler pins exact Python-node revision/checksum and safe execution metadata; never source.
- Runtime re-resolves organization, active policy and checksum before dispatch and validates input
  and returned patch again. Decide via ADR whether disable blocks only new runs or also queued/in-flight
  execution.
- Runner output is untrusted and merges only through the Phase 2.6 typed state-mapping/protected-key
  policy.
- Preserve all existing managed-node behavior and fixtures. Studio labels “Yönetilen node” versus
  “Python node” and shows their different lifecycle.

### P2.6.9A — Bounded authoring-context service

Build one server-side service scoped from the authenticated Studio scenario, never from client
tenant fields. It produces a deterministic, stable-ordered, checksummed snapshot with independent
section and total byte/token/item limits.

Included safe context:

- scenario type/name/purpose and safe organization/project names;
- current reviewed workflow LLM guide, exact node config contracts and platform limits;
- active managed/Python node `node_ref`, execution class, display name, description and bounded
  config/input/output schema summaries;
- active tool-binding roles, safe description/risk/side-effect/approval summary, but no definition
  destination or secret reference;
- release-available prompt/model/retrieval role names and safe capability metadata;
- scenario document-set binding names/counts and retrieval availability, but no document content;
- input/output contract schemas within explicit bounds;
- safe workflow draft/candidate/published/candidate-release/active-release metadata needed for the
  authoring decision.

Excluded context:

- secret/credential/reference values, endpoints/hosts/paths, headers and network policy;
- Python source, test inputs/outputs and runner internals;
- documents, retrieved chunks and document metadata beyond the approved capability summary;
- foreign-organization records, user lists, audit content and unrelated operational data;
- raw model profile endpoint or credential metadata.

Where a safe description/purpose field does not exist today (for example current tool bindings), add
an explicit bounded reviewed metadata field or omit the description. Never synthesize it from an
endpoint, secret-bearing manifest or unrelated operational record.

If any section exceeds its limit, use an explicit deterministic truncation/summary marker; never
silently cross tenant scope or drop authorization-relevant capability identity.

### P2.6.9B — Structured model contract and conformance

Send separate messages/inputs:

1. immutable server system instructions and output schema;
2. server-generated authoring context marked as untrusted descriptive data; and
3. user natural-language request marked untrusted and non-authoritative.

The response is a strict discriminated union:

```json
{
  "status": "workflow_candidate",
  "workflow": {}
}
```

or:

```json
{
  "status": "capability_missing",
  "required_capability": "number.multiply",
  "suggested_custom_node": {
    "display_name": "Sayıyı katsayıyla çarp",
    "purpose": "Bir input değerini belirlenen katsayıyla çarpar",
    "input_summary": "...",
    "config_summary": "...",
    "output_summary": "..."
  }
}
```

- Do not allow an invented node/tool/prompt/model/retrieval/schema ref even if the candidate is
  otherwise valid JSON.
- Validate references against the returned snapshot checksum and current live authorized state.
- `capability_missing` may initialize an unsaved Python-node scaffold in Studio. AI-generated source,
  if separately requested and permitted by a dedicated prompt contract, remains transient and uses
  the same draft/test/review lifecycle. AI cannot submit review, approve, activate, publish, compile,
  evaluate or promote.
- Audit model profile ID, context/prompt-contract checksums, counts, bytes, tokens, status and safe
  reason codes only.

### P2.6.9C — Studio transient candidate and explicit save

- Embed the planner in the scenario-scoped Studio rather than the cross-project draft list.
- Generate directly into transient graph/JSON state; run canonical diagnostics immediately.
- Preserve invalid bounded JSON text for repair and bind diagnostics to node/edge/JSON Pointer where
  the canonical validator can provide a pointer. Graph rendering is best effort; JSON remains the
  lossless repair surface.
- Show dirty navigation/reload warning. Initial implementation stores transient state in memory only.
- Before save, allow display-name edit only; logical ID/slug/revision are absent from the UI.
- On save, server allocates an ID with `allocate_identifier`, rewrites `metadata.id`, locks
  organization/project/scenario from the route, authorizes and validates atomically, then creates a
  `WorkflowDraft`.
- If a scenario already has drafts, require one explicit intent:
  - update selected existing draft using its expected revision; or
  - create a copy with a new server-generated ID.
- Never silently choose or overwrite a draft. Preserve local transient work on `stale_revision`.
- Keep save, publish, release compile, eval and promotion as separate existing lifecycle actions.
- Provide Turkish-first states for generating, valid/invalid candidate, capability missing, timeout,
  rate limit, invalid JSON, `outcome_unknown`, stale draft and capability drift.

### P2.6.9D — Unified Scenario Studio information architecture

Within one scenario context, expose clearly separated panels/statuses for:

- AI planner and transient candidate;
- graph, JSON and pointer-bound diagnostics;
- managed/Python node catalog and inline Python-node draft/review status;
- saved mutable workflow drafts;
- immutable published artifacts and exact node pins;
- candidate/active releases, eval and promotion status.

Opening the inline Python-node drawer does not navigate away or mutate the transient workflow. A
pending suggested node appears as an unresolved capability marker, but the workflow cannot be saved
or published until an active exact ref replaces it.

## Non-goals

- Executing Python in web, Celery runtime, model provider or existing managed-node processes.
- Tenant-provided wheels, packages, native extensions, container images or dependency installation.
- Network/filesystem/process/secret access for Python nodes.
- Organization admins self-approving node code.
- AI auto-save, auto-review, auto-activation, publish, release, eval or promotion.
- Sending source, endpoints, secrets or document content to the authoring model.
- Persistent browser recovery of transient AI output in the first delivery.
- Replacing managed nodes or removing their current compatibility.

## Acceptance criteria

- [ ] Isolation spike and ADR approve the minimum separate runner; stronger sandboxing is required
  only when the spike/deployment policy demands it.
- [ ] Every submitted revision has a checksum/rule-set-bound automated security report; critical
  findings block approval and warnings require a platform-admin rationale.
- [ ] Author/reviewer/auditor authorization matrix is enforced server-side with cross-tenant tests.
- [ ] Review/activation binds exact immutable revision and checksums; content changes invalidate it.
- [ ] Only active exact Python-node refs can save/publish/compile/run; managed nodes remain compatible.
- [ ] Runner has no ambient platform authority and enforces wall/CPU/memory/PID/output limits.
- [ ] Server context is tenant/scenario scoped, bounded, deterministic and excludes forbidden data.
- [ ] Model outputs only supplied refs or a structured capability-missing result.
- [ ] Generation creates no DB state; explicit save allocates identifiers server-side.
- [ ] Existing draft update/copy is explicit and optimistic concurrency prevents silent overwrite.
- [ ] Studio presents all lifecycle states distinctly in Turkish-first UI.
- [ ] Publish/release/eval/promotion remain separate governed actions.

## Affected components

- `apps.builder`: drafts, review UI/API, transient Studio flow, identifiers and diagnostics.
- `apps.workflows`: catalog/compiler/release resolution, isolated runner adapter and runtime guards.
- `apps.artifacts` / `apps.releases`: exact revision/checksum pinning without source disclosure.
- `apps.orchestration`: bounded context and structured authoring-provider contract.
- `apps.tenancy` / `apps.identity`: existing identifier and role predicates; new explicit platform
  review predicates if required.
- `apps.audit` / `apps.observability`: safe lifecycle events and bounded metrics/traces.
- `frontend`: unified Scenario Studio panels and transient state.
- deployment: separate sandbox runner topology only after dependency/runtime approval.

## Interfaces affected

- Additive operator-only Studio APIs for Python-node draft/review/test/status and context-aware
  generation/save. No consumer API is planned.
- Existing AI candidate endpoints may be deprecated after Studio parity; do not maintain two active
  authoring experiences indefinitely.
- Existing workflow/custom-node artifact compatibility is preserved for managed nodes.

Authentication/authorization and any runner/network interface changes require explicit owner
approval before implementation.

## Data impact

- Additive tenant-owned draft/revision/review/test/activation tables with direct organization lineage
  and PostgreSQL FORCE RLS/non-owner verification.
- Source and test payload storage requires encryption/retention decision; no source in audit/logs.
- AI candidates remain non-persistent until explicit save.

## Security impact

Tenant Python is intentional remote-code execution against the runner. Isolation failure is a
critical platform risk. Implementation is blocked until the ADR proves the minimum separate
process/container, credential, network, filesystem and resource-limit boundary. gVisor/Kata/microVM
is optional hardening unless the spike requires it. Automated and admin review are mandatory but do
not replace runtime isolation. The detailed threat model is
[`threat-model.md`](threat-model.md).

## Authorization impact

- Author: existing `can_author_scenarios` within active organization/scenario lineage.
- Organization admin: safe organization metadata/status view; no approval or source by default.
- Platform admin: source review and lifecycle decisions.
- Auditor: safe read-only metadata/history.
- Runtime consumer authority does not grant source access or node activation rights.

Changing these predicates is an explicit authorization change and needs approval before code.

## Observability impact

- Audit create/edit/test-submit/automated-review/admin-review/activate/disable and safe execution
  outcomes with exact revision/checksum, rule-set revision, actor, target, decision, outcome and
  trace ID.
- Audit AI request/result using profile/context/contract checksums, counts/tokens and status only.
- Never log/audit source, secret, raw test input/output, document content or model raw output.
- Metrics need bounded labels for queue, sandbox termination reason, review state and AI status.

## Migration impact

Additive models and constraints are expected. No destructive migration is planned. The repository is
unreleased and dummy data may be reset under the separately approved Phase 2.6 procedure, but this
task does not perform or implicitly authorize a reset.

## Dependencies

- Phase 2.6 P2.6.0 contracts and P2.6.1 typed state mapping for runtime merge.
- Existing Scenario Studio, workflow compiler, release lifecycle, tool approval and identifier
  allocator.
- Explicit approval for any production sandbox dependency/image/service or network/IAM change.

Parallelization:

- Lane E1 isolation spike/ADR and E2 control-plane schema/UI may proceed in parallel after their
  shared checksum/state/role contracts are frozen; no source execution before E1 approval.
- Lane F1 context service/conformance and F2 transient Studio UX may proceed in parallel against
  shared fixtures.
- E and F may proceed independently. F consumes only a versioned safe Python-node catalog fixture
  until E publishes that contract.
- Runner/runtime integration and final unified Studio integration are sequential merge gates to
  avoid concurrent edits to compiler/runtime core.

## Implementation steps

1. Approve this plan, threat model and explicit authorization matrix.
2. Run minimum-runner isolation spike; write and approve runner ADR, optional hardening decision and
   protocol/resource budgets.
3. Freeze Python-node lifecycle/checksum/automated-review/public-catalog schemas and AI context/result
   schemas.
4. Implement Python-node control plane, identifier allocation and automated review without runtime
   workflow execution.
5. Implement isolated test runner adapter only after ADR/dependency approval.
6. Implement compiler/release/runtime integration and managed-node compatibility.
7. Implement bounded context service and structured provider contract.
8. Implement transient Studio planner, pointer diagnostics and explicit save/update/copy.
9. Integrate inline Python-node suggestion/review status into Studio.
10. Add eval, audit, metrics, retention/runbook, deployment gates and complete verification.

## Test plan

- Model/service/state-machine unit and property tests for exact keys, bounds and checksum transitions.
- Role matrix, authn, disabled organization, cross-project/scenario and cross-tenant denial tests.
- Review stale-checksum, self-approval, mutation-after-review, disable and historical-lineage tests.
- Automated review parse/import/forbidden-operation/static-rule/schema/resource probes, critical
  non-bypass, warning-rationale and rule-set-version invalidation tests.
- Sandbox escape corpus: imports/reflection/deserialization, fork/process, filesystem, network, env,
  resource exhaustion, infinite loop, output bomb and malformed JSON.
- Runner crash/redelivery/cancel/timeout/`outcome_unknown` and checksum substitution tests.
- Managed-node regression and exact release pin tests.
- Context golden snapshots, ordering/bounds/truncation, foreign data, endpoint/secret/source/document
  non-disclosure and invented/stale reference tests.
- Assert generation performs zero DB writes; save performs one authorized atomic create/update.
- Transient invalid JSON, graph fallback, pointer diagnostics, beforeunload, update/copy and stale
  revision frontend tests.
- SQLite suite plus PostgreSQL non-owner RLS and real queue/runner recovery tests.
- Full repository gates and Turkish authenticated browser journey.

## Rollout plan

- Separate disabled-by-default flags for Python-node authoring, testing, runtime execution and
  context-aware AI Studio.
- Deploy control plane before runner; no active Python revisions while runner is unavailable.
- Provision runner with no network/credentials and verify escape/resource probes in non-production.
- Enable for one organization/scenario with strict quotas and kill switch.
- Enable Studio AI independently; generation remains transient and non-publishing.
- Promote only after eval and operations dashboards/runbook are ready.

## Rollback plan

- Disable new Python tests/executions and AI generations independently.
- Disable active Python revisions without deleting source/review/history.
- Existing managed nodes and releases continue through their original path.
- Unsaved browser candidates are discarded; saved drafts remain mutable data.
- Roll back code with forward-fix migrations; do not destructively remove referenced review/run data.

## Risks

- Sandbox escape or shared runner credentials compromise the platform.
- Reviewer overload or superficial approval creates unsafe active code.
- Source may contain credentials despite UI warnings; scanning/redaction policy is required.
- Context may leak tenant data or become too large/costly.
- Model may invent or reuse stale capabilities despite prompt instructions.
- Inline authoring can blur transient/draft/published/release state.
- Parallel implementation can conflict in builder/compiler files without frozen contracts.

## Open questions

1. Minimum runner topology, whether stronger sandbox hardening is justified, source storage
   encryption and runner image patch ownership.
2. Exact stdlib module allowlist and whether any module subsets require different risk tiers.
3. Source-view permission for organization admins and auditors; recommended default is metadata only.
4. Whether platform approval atomically activates or activation is a second explicit action.
5. Disable semantics for queued/in-flight executions.
6. Exact per-section context budgets and schema-summary algorithm.
7. Whether AI may generate Python source only after an explicit second user action; recommended yes.
8. Whether pointer-rich diagnostics require a compiler diagnostic contract change shared by all
   authoring paths.

## Status

Planned. Implementation has not started. Isolation spike/ADR and authorization approval are hard
gates.

## Completion criteria

Map to the repository Definition of Done: approved ADR/threat model, implemented exact contracts,
authorization/RLS/sandbox/non-disclosure evidence, full checks, current-state documentation,
operational kill switches/runbook, owner Turkish Studio review and accepted residual risks.
