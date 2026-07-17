# P2.6.8 Isolation Spike

## Scope and safety boundary

This spike evaluates host/runtime capabilities and defines future probes. It does not run tenant
source, add a runner, change Compose/OpenShift topology or authorize production execution. The only
executed container used a fixed `python:3.13-slim` image with inert capability checks, no network,
no platform volumes and no credentials.

## Evidence from the current environment

Run on 2026-07-16 against Docker Engine 27.3.1, Linux/amd64:

| Property | Evidence | Assessment |
| --- | --- | --- |
| Runtime | Default `runc`; no gVisor/Kata runtime listed | Stronger sandbox is unavailable locally |
| Kernel controls | cgroup v2; OCI reports CPU/memory/PID and seccomp feature support | Necessary primitives exist |
| Seccomp posture | daemon security option reported `seccomp,profile=unconfined` | Fails proposed production baseline |
| Non-root | probe returned UID/GID 65532 | Pass for local primitive |
| Root filesystem | write to `/probe` returned `OSError` under `--read-only` | Pass for local primitive |
| Scratch | 1 MiB `noexec,nosuid` tmpfs accepted a test write | Pass for bounded scratch primitive |
| Network | connection under `--network none` returned `OSError` | Pass for local primitive, not an OpenShift NetworkPolicy proof |
| Resource flags | `--cpus 0.25 --memory 64m --pids-limit 16` accepted | Configuration proof only; enforcement corpus still required |
| Environment | only base-image runtime variables were visible | Application credential absence proven for this inert invocation only |
| Live topology | Compose showed PostgreSQL, Redis and MinIO healthy; no application/runner service | Confirms runner is not implemented |

The canonical application Compose anchor injects database, Redis, object-store and model secrets and
mounts the repository. It must never be reused by a Python execution sandbox. Existing OpenShift
drafts use non-root/read-only/RuntimeDefault patterns and default-deny policies, but there is no
runner workload or target-cluster evidence.

## Decision matrix

Scores are relative for the first release: 1 is weakest/highest cost, 5 is strongest/lowest cost.

| Candidate | Isolation strength | Platform fit | Startup/cost | Evidence now | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| In-process/subinterpreter | 1 | 5 | 5 | 5 | Reject: shares application authority |
| Long-lived privileged/shared worker | 2 | 4 | 4 | 3 | Reject: ambient credentials/queue blast radius |
| Per-call locked-down OCI sandbox | 3 | 5 | 4 | 3 | Recommended minimum, conditional on target probes |
| gVisor | 4 | 3 | 3 | 1 | Evaluate if available; no default dependency |
| Kata Containers | 5 | 2 | 2 | 1 | Evaluate for policy/high-risk tier |
| Firecracker/microVM | 5 | 1 | 1 | 1 | Defer unless shared-kernel risk is rejected |

## Recommended minimum runner profile

- Separate runner control plane and dedicated queue; one short-lived sandbox for one execution.
- Digest-pinned minimal image, numeric non-root user, `allowPrivilegeEscalation: false`, drop `ALL`,
  read-only root, RuntimeDefault or stricter seccomp and platform LSM.
- No application anchor/environment, service account token, hostPath, repository, Docker socket,
  device or credential mounts.
- Default-deny ingress/egress including DNS and metadata; only the control plane transports a
  bounded one-time request/result without exposing its credential to the sandbox.
- Hard admission/runtime caps. Initial values are deliberately conservative proposals, not approved
  SLOs: source 64 KiB; each schema 64 KiB/16 depth; request 256 KiB; response 256 KiB; wall 5 s;
  CPU 2 s; memory 128 MiB; 16 PIDs; scratch 4 MiB; stdout/stderr captured only into a 16 KiB
  redacted diagnostic buffer and never persisted raw; per-tenant concurrency 2.
- Kill on any cap violation. No automatic retry for `outcome_unknown`; pure deterministic calls may
  be redelivered only when the protocol proves the prior execution never started or returns the
  exact idempotent committed result.

These numeric limits require performance/product owner approval and target-runtime measurement.

## Runner protocol probe plan

Each request must bind `protocol_version`, opaque `execution_id`, organization-safe internal
reference, exact revision checksum, security-report checksum, runner image digest, input checksum,
expiry, attempt and idempotency key. Source and raw input are encrypted transport fields, never
audit fields. The response binds all request checksums plus outcome, output checksum, bounded
resource counters and stable reason code.

Probe the following before runtime implementation is enabled:

1. valid synthetic pure function returns schema-valid JSON and exact response binding;
2. modified revision/input/image/report checksum is rejected before start;
3. expired, replayed and duplicate execution IDs cannot repeat work;
4. cancellation before start prevents dispatch; cancellation during execution kills the sandbox;
5. lost response classifies `outcome_unknown` and is not blindly retried;
6. malformed, oversized, schema-invalid or protected-key output is rejected;
7. runner/control-plane restart reconciles durable intent without trusting queue state;
8. concurrency quotas isolate tenants and prevent starvation;
9. audit failure for activation/disable fails closed; telemetry failure does not authorize work.

## Negative sandbox corpus

The inert manifest is `fixtures/python-node-negative-sandbox-corpus.json`. A future harness must
materialize each `source_template` only inside the approved sandbox and assert the expected control:

- static blocks: dynamic execution/import, reflection/dunder, filesystem, process/thread, socket,
  unsafe serialization and non-allowlisted modules;
- runtime containment: environment, filesystem/root/device/host mount, DNS/metadata/internet,
  fork/PID, CPU/wall, memory, scratch and output limits;
- protocol validation: replay, expiry, checksum substitution, malformed response and cancellation.

No corpus case may run in Django, Celery, the managed-node executor or CI until the isolated harness
and explicit runtime approval exist.

## Target-environment acceptance gate

The runtime branch remains blocked until a non-production deployment records:

- effective pod/container security context and admission decision;
- runtime class, seccomp/LSM profile, kernel/node-pool ownership and no silent fallback;
- effective default-deny network policy using DNS, metadata, private and public egress probes;
- absence of service-account token, credentials, proxy variables, host mounts and devices;
- enforced CPU/wall/memory/PID/scratch/output/concurrency termination reason codes;
- image digest/signature/SBOM/vulnerability scan and patch/rollback ownership;
- complete negative corpus results and cleanup/reconciliation after crash/cancel;
- measured cold-start, throughput and saturation behavior.

If any shared-kernel control cannot be proven or the owner rejects residual kernel risk, select and
re-spike gVisor/Kata/microVM before activation.
