# Task Plan: OpenShift deploy portability hardening

## Task summary

Turn the live bundled-stack OpenShift recovery changes into portable, fail-closed product changes
without weakening the managed-service Helm installation contract.

## Background

A restricted OpenShift environment required an approved registry mirror, Binary BuildConfigs, a
standalone static-image build, database readiness coordination, and probe changes. The live stack
was recovered, but the environment diff hard-coded one registry/release and changed Helm hooks and
readiness semantics in ways that do not generalize safely.

## Scope

- Parameterize Docker base images while preserving upstream defaults.
- Add reusable OpenShift ImageStream/Binary BuildConfig resources without automatic Binary triggers.
- Add a standalone static Dockerfile for builders that cannot select a multi-stage target.
- Preserve pre-install/pre-upgrade hooks for managed external databases and add Helm-managed,
  revisioned initialization Jobs for the bundled stack.
- Wait for PostgreSQL with a digest-pinned probe image and gate workloads on applied migrations plus
  active, configuration-matching model and embedding profiles.
- Keep HTTP semantic readiness and fix virtual-host probes with an explicit Host header.
- Update Secret generation, schemas, examples, tests, and operator documentation.

## Non-goals

- No live cluster mutation, image build/push, registry login, or credential access.
- No production/HA promotion of the bundled stack.
- No provider, authentication, tenant-isolation, public API, or database-schema change.
- No environment-specific route, repository, digest, credential, or release value committed.

## Acceptance criteria

- Canonical builds work with upstream defaults and accept approved mirror overrides.
- Binary BuildConfigs require an explicit streamed source and share one parameterized release id.
- Managed-service installs retain blocking pre-hooks; bundled installs remain compatible with
  `--atomic --wait --wait-for-jobs` without a post-install/workload deadlock.
- Unexpected bootstrap output/configuration and disabled or mismatched profiles fail closed.
- Readiness continues to exercise `/v1/health/ready`; probes no longer use pod-IP Host headers.
- Probe images are non-empty and digest-pinned by schema and examples.
- Offline chart, manifest, security-invariant, shell, and relevant Python tests pass.

## Affected components

- `deploy/Dockerfile`, `deploy/static.Dockerfile`, `deploy/postgres-openshift.Dockerfile`
- `deploy/openshift/build/`
- `deploy/helm/agenthub` and `deploy/helm/agenthub-stack`
- OpenShift/Helm operational documentation and deployment tests

## Interfaces affected

Helm values gain database initialization mode and probe-image configuration. Docker builds gain
optional base-image build arguments. These are deployment/operator interfaces, not public product
APIs.

## Data impact

No schema or data rewrite. Initialization may create missing immutable platform profiles; existing
profiles must match the declared revision/configuration and be active.

## Security impact

Preserves arbitrary-UID restricted-SCC controls, immutable runtime images, external Secrets, and
least-privilege database roles. The probe image becomes an explicitly pinned production image input.

## Authorization impact

Profile creation continues through the platform-admin management-command/service boundary. Workload
gates perform read-only database checks with the runtime role.

## Observability impact

Initialization and gates emit bounded readiness reasons without credential or endpoint-secret data.
Unexpected bootstrap state exits non-zero instead of silently succeeding.

## Migration impact

No Django migration. Migration execution ordering changes only for bundled Helm topology.

## Dependencies

No Python or frontend package dependency. The deployment adds an operator-supplied, digest-pinned
PostgreSQL client image for `pg_isready`.

## Implementation steps

1. Add portable build inputs and generic OpenShift Binary build resources.
2. Add conditional hook/managed-Job initialization and shared database wait/gate helpers.
3. Make bootstrap profile reconciliation exact and fail closed.
4. Restore semantic HTTP probes with a safe Host header.
5. Close values schemas and update examples/runbooks.
6. Add tests and record verification evidence.

## Test plan

- Docker/build manifest invariants and no environment-specific registry values.
- Helm lint/template for managed and bundled modes, including strict schema rejection cases.
- YAML parsing and restricted-SCC/resource/image-digest invariants.
- Bootstrap/gate render assertions for active and exact profile checks.
- Relevant observability/deployment Python tests and shell syntax checks.

## Rollout plan

Build immutable application/static/PostgreSQL-probe images, resolve digests, run strict lint and
server-side dry-run, back up bundled data, then use `helm upgrade --install --atomic --wait
--wait-for-jobs`. Validate Jobs, profile state, HTTP readiness, console, static manifest, and workers.

## Rollback plan

Restore the previous application/static/config revision only after reviewing applied migrations.
Helm rollback does not reverse migrations or profile creation. Environment overlays and external
Secrets remain independently managed.

## Risks

- Normal Job naming/cleanup must remain correct across Helm revisions.
- Gate queries must be readable by the runtime DB role on the target platform.
- Standalone and canonical static Dockerfiles can drift without parity tests.
- Target-cluster admission, registry trust, CNI and quota remain live acceptance gates.

## Open questions

None blocking. The bundled stack uses Helm-managed revisioned Jobs; managed external DB installs keep
the existing pre-hook contract. The durable decision is recorded in
[ADR-0018](../../../adr/0018-portable-openshift-build-and-database-initialization.md).

## Status

Verified offline on 2026-08-28. Target-cluster build, server-side admission and live rollout remain
environment acceptance gates.

## Completion criteria

Implementation, documentation, automated verification, final staff/security/SRE review and
master-plan update are complete. Live OpenShift evidence is intentionally not claimed.
