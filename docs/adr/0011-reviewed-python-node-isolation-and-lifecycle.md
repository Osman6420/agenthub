# ADR 0011: Reviewed Python Node Isolation and Lifecycle Boundary

- **Status:** Accepted
- **Date:** 2026-07-17

## Context

AgentHub currently supports `CustomNodeDefinition` records whose exact package-version executors
are installed and registered by the platform and run in the trusted workflow process. Phase 2.6
adds a different capability: scenario-author Python source. Reusing the current executor would run
untrusted tenant code inside Django/Celery authority and is prohibited.

This ADR freezes the minimum boundary and lifecycle contract needed by the later P2.6.8 runtime
branch. It does not authorize tenant-source execution, add a service or dependency, change
authorization, or deploy a sandbox.

## Decision drivers

- Contain malicious or compromised tenant source without relying on Python language restrictions.
- Keep database, broker, object-store, secret-store and network authority outside the sandbox.
- Bind review, activation and execution to one immutable revision and canonical checksum.
- Preserve existing managed-node behavior and public catalog compatibility.
- Make resource exhaustion, replay, cancellation and ambiguous outcomes observable and testable.
- Avoid selecting gVisor, Kata Containers or a microVM without platform-specific evidence.

## Considered options

| Option | Isolation | Operational fit | Decision |
| --- | --- | --- | --- |
| Execute in web/runtime/Celery or a Python subinterpreter | Shared process, credentials and kernel authority | Simple but catastrophic blast radius | Rejected |
| Long-lived generic runner sharing application queues/credentials | Process separation but ambient authority remains | Easy to operate, unsafe boundary | Rejected |
| Fixed credentials-free OpenShift runner pool; fresh process per execution | Dedicated pod boundary from AgentHub; reviewed executions share a recycled pod sequentially | Fits target OpenShift permissions and avoids per-call pod scheduling | Accepted first release |
| Per-execution locked-down OCI pod/job | Stronger namespace/cgroup/seccomp reset for every call | Requires workload-create/delete authority and scheduling latency unavailable in the target operating model | Deferred hardening |
| gVisor sandboxed OCI runtime | Additional syscall mediation | Not installed or measured in the current environment | Conditional hardening |
| Kata Containers | Lightweight VM boundary | Requires runtime/node-pool and operational changes | Conditional hardening |
| Firecracker or other microVM per execution | Strongest evaluated tenant/kernel separation | Highest image, scheduling and observability cost | Conditional high-risk tier |

## Decision

### Terminology and compatibility

- **Managed node** means the existing platform-installed `custom_node_definition` plus registered,
  exact-package-version executor. Its persisted type and runtime behavior are unchanged.
- **Python node** means scenario-author source governed by the lifecycle below and executable only
  through the isolated runner. It never uses the managed-node in-process registry.
- Catalog entries expose `execution_class: managed | python`. The workflow family may remain
  `custom`, but the execution class is explicit and cannot be inferred from a display label.

### Minimum runner

Use a dedicated OpenShift Deployment with four long-lived runner pods behind an internal ClusterIP
Service. AgentHub receives no Kubernetes workload-create/delete permission. Each pod accepts at most
one execution at a time and launches a fresh short-lived Python process. The supervisor exits after
20 executions or 15 minutes, and immediately after cleanup/resource-integrity failure; OpenShift's
normal container restart supplies a clean writable layer. Full pod replacement remains an operator
rollout, not application authority.

This is an explicitly reviewed-code execution tier, not a general untrusted-Python service. Sharing
one recycled pod sequentially is weaker than per-execution OCI isolation. The accepted first-release
boundary relies on mandatory automated review, exact platform-admin review, a credentials-free pod,
fresh processes and aggressive recycling. A separate pod/job or stronger runtime is required if
arbitrary unreviewed code, native extensions or a stronger tenant/kernel boundary is later admitted.

Every runner pod and execution process must have all of these properties:

- fixed digest-pinned minimal image and interpreter/rule-set identity;
- numeric non-root UID/GID, no privilege escalation, all Linux capabilities dropped;
- read-only root filesystem; bounded `noexec,nosuid,nodev` scratch only; no host, Docker socket,
  service-account or application volume mounts;
- empty/minimal allowlisted environment and no database, Redis, object-store, registry, cloud,
  proxy, DNS, secret-store or application credentials;
- infrastructure-enforced default-deny ingress and egress, including DNS and metadata endpoints;
- cgroup v2 CPU/memory/PID limits, wall-clock deadline, scratch/output limits and bounded tenancy
  concurrency; limit breach terminates the sandbox;
- `RuntimeDefault` or stricter versioned seccomp, default AppArmor/SELinux confinement where the
  platform supports it, and no unconfined fallback;
- unique execution identity, bounded request/response, expiry, request checksum, idempotency and
  response binding; the tenant cannot address the runner directly; no automatic retry after a
  transport timeout or other `outcome_unknown`;
- image admission, signature/SBOM/vulnerability policy and a named patch/rollback owner before
  production enablement.

The base runner has no ServiceAccount token, Secret, ConfigMap containing platform coordinates,
database/broker/object-store access, DNS or egress. Only the runtime-worker pod selector may reach
its Service. Authenticated encrypted transport must be supplied and attested by the target
OpenShift service-mesh overlay without mounting its private identity into the runner container.
The supervisor stores or logs no source, raw input/output or stderr. Source and input exist only in
bounded request/child-process memory for the execution and are released before the next request.

The local Docker spike proved that non-root UID, read-only root, isolated bounded scratch,
`--network none`, and CPU/memory/PID flags are available. It did not prove production network
policy, kernel escape resistance, seccomp enforcement, cancellation or concurrency behavior. The
local daemon reported `runc` and `seccomp,profile=unconfined`; that configuration fails this ADR.

### Stronger sandbox decision

gVisor, Kata or a microVM is not a default dependency for the first release because none is
installed or measured in the current environment. Before production activation, the platform and
security owners must rerun the corpus on the target OpenShift runtime. Stronger isolation becomes
mandatory if policy requires a tenant/kernel boundary, RuntimeDefault/LSM/network isolation cannot
be proven, native extensions or broader modules are admitted, the shared-kernel residual risk is
not accepted, or escape probes find a bypass. High-risk tenants may be assigned a stronger tier in
a later ADR; silent fallback to `runc` is forbidden.

### Revision, review and activation

- A mutable `PythonNodeDraft` is tenant/scenario-owned. Submission creates an immutable,
  server-numbered `PythonNodeRevision`.
- The canonical revision checksum covers a versioned envelope containing normalized UTF-8 source,
  config/input/output schemas, requested module set and contract version. Display metadata is
  separately checksummed when it affects public catalog output.
- `PythonNodeSecurityReview` binds revision checksum, exact rule-set ID/checksum, runner image
  digest and probe-policy checksum. Scanner failure is blocking. Critical findings cannot be
  overridden. Warning acceptance requires a bounded platform-admin rationale.
- `PythonNodeReview` binds the revision checksum and security-report checksum. The submitting author
  cannot review. A content or rule-set change requires a new report and decision.
- Approval does not activate. `PythonNodeActivation` is a second explicit, audited,
  platform-admin action bound to the approved revision, review and security-report checksums. This
  avoids accidental activation and supports separation of deployment readiness from code review.
- Disable is an append-only lifecycle decision. It immediately blocks new publish, release compile,
  run start and queued-but-not-started dispatch. Already-started sandboxes may finish under their
  pinned revision; their result is accepted only if the run was authorized before disable and the
  durable transition remains non-terminal. An emergency kill switch cancels them separately.
  Disable never deletes lineage.
- Existing releases already pinned to a disabled revision remain historical evidence and cannot
  start a new run. Re-enable is not an in-place toggle; it is a new explicit activation decision.

### Automated review contract

The mandatory initial rule set is repository-owned and dependency-free unless a production scanner
is separately approved. It deterministically checks parse/syntax, source/schema/module bounds,
closed imports, forbidden builtins and dynamic code loading, dunder/reflection, filesystem,
process/thread, socket/network, unsafe deserialization and schema fixtures. Isolated resource probes
cover deadline, CPU, memory, PID, scratch and output limits.

Reports are content-free: stable finding code, severity, location coordinates (no source excerpt),
count, rule-set checksum, probe outcome/reason code and overall `pass | blocked | error`. The
contract schema is stored with the P2.6.8 task. Static review remains defense in depth and never
substitutes for runtime isolation or human review.

### Source storage and viewing

Recommend a private, content-addressed object encrypted at rest with a platform-managed KMS key,
random non-derivable locator, integrity checksum and tenant/revision metadata in PostgreSQL. The
object store must deny public access, runner listing and cross-tenant lookup. Source is not placed in
workflow JSON, artifact bodies, release manifests, catalog responses, audit, logs or traces.

Only a separately approved `python_node_source_reviewer` platform role may view exact source for an
assigned review; platform superuser status alone should not silently grant bulk source export.
Scenario authors may view their authorized draft/revision source. Organization admins and auditors
receive metadata/checksums only. Source view is audited fail-closed without recording content.

Proposed retention: mutable abandoned drafts 30 days after explicit soft-delete; rejected or
changes-requested revision source 90 days after decision; approved/active/disabled revision source
for the longest of tenant policy, active references and seven years of governance lineage; raw test
input/output at most 24 hours; execution payload only for sandbox lifetime. Legal hold and active
pins suspend purge. Actual periods, KMS topology and source-view predicates require data/security
owner approval before persistence implementation.

### Public catalog metadata

P2.6.9 may consume only the versioned safe contract in
`python-node-public-catalog.schema.json`. It includes opaque ref, execution class, lifecycle status,
display/purpose, exact active revision/checksum and bounded schema summaries. It excludes source,
module requests, findings, reviewer identity/rationale, storage locators, endpoints, image/runtime
internals and authority fields. `python` entries are returned only when active and tenant/scenario
authorized; `managed` entries preserve their current availability rules.

## Security consequences

Tenant Python remains intentional hostile-code execution against a shared kernel. Language review
cannot prove safety. The chosen boundary removes ambient platform authority and constrains blast
radius, but production activation still requires target-runtime escape/resource evidence and formal
acceptance of shared-kernel risk or selection of stronger isolation.

Review, activation, disable and source view are authorization changes and remain owner-gated.
Required audit evidence commits with the lifecycle transition or the action fails closed.

## Operational consequences

A dedicated four-replica Deployment, image lifecycle, concurrency-one admission, capacity limits,
recycling, reconciliation and kill switch are required. The application does not manage pods.
Service availability is not execution authority. Metrics use bounded reason codes for starts,
terminations, saturation and resource-limit breaches; source and raw payloads are never labels or
telemetry fields.

## Data and privacy consequences

Source may contain confidential logic or accidentally embedded secrets. Storage encryption,
minimal role-based viewing, short raw-payload retention, legal hold and auditable purge are required.
Checksums are safe metadata but remain tenant-scoped.

## Positive consequences

- Existing managed nodes stay compatible and unmistakably separate.
- A minimum deployable boundary is defined without adding a production dependency.
- Exact revision/report/review/activation binding prevents stale or swapped approvals.
- P2.6.9 receives a stable, source-free catalog contract.

## Negative consequences

- Shared-kernel OCI isolation retains kernel-escape risk.
- Sequential pod reuse retains more cross-execution residual risk than per-execution OCI workloads.
- A saturated four-pod pool returns a bounded capacity error instead of queueing unbounded work.
- Two explicit admin decisions add lifecycle friction.
- KMS/object-store and source-view details remain deployment/authorization approval gates.

## Migration impact

None in this branch. The runtime branch may add only additive tenant-owned records with direct
organization lineage, same-tenant constraints and FORCE RLS/non-owner verification after approval.

## Rollback considerations

Authoring, test and runtime flags remain independently disabled by default. Disable new dispatch
without deleting drafts, revisions, reports, decisions or historical run pins. Roll back code with
forward-fix migrations; never reinterpret an existing revision under a different contract or image.

## References

- [Phase 2.6 plan](../planning/phase-2-6-plan.md)
- [P2.6.8/P2.6.9 task plan](../tasks/phase-2-6-authoring-and-python-nodes/plan.md)
- [Isolation spike](../tasks/phase-2-6-authoring-and-python-nodes/isolation-spike.md)
- [Review and catalog contracts](../tasks/phase-2-6-authoring-and-python-nodes/python-node-contracts.md)
- [ADR 0008](0008-durable-workflow-transition-state-machine.md)
- [ADR 0010](0010-workflow-dataflow-join-wait-and-human-task-contract.md)
