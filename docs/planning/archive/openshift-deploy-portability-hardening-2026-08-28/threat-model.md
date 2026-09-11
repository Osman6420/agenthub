# Threat Model: OpenShift deploy portability hardening

## Assets

Deployment integrity, immutable image identity, database schema/profile state, provider and
infrastructure credentials, bootstrap recovery authority, and tenant application availability.

## Actors

Authorized namespace operator, Helm/`oc` clients, OpenShift build service, migration/bootstrap Jobs,
application workloads, and cluster ingress.

## Entry points

Docker build arguments, Binary build streams, Helm values, external Secret references, Job commands,
HTTP health probes, and provider profile configuration.

## Trust boundaries

- Operator workstation to OpenShift API and build service.
- Approved mirror/internal registry to image builds and pods.
- Helm non-secret values to external namespace Secrets.
- Migration role to schema; runtime role to application/profile state.
- Kubelet HTTP probes to Django virtual-host validation.

## Data classifications

Image/release/profile metadata is operational internal data. Passwords, API keys, database URLs and
bootstrap credentials are secrets and must remain outside Helm values, build contexts and logs.

## Authentication

Existing `oc`/registry authentication and namespace Secret access remain platform responsibilities.
Application authentication is unchanged.

## Authorization

No Kubernetes RBAC is added. Pods do not mount service-account tokens. Profile registration remains
limited to the existing platform-admin service boundary.

## Tenant isolation

No tenant tables or query paths change. Initialization touches only platform profile catalogs and the
bootstrap platform actor.

## External systems

Approved registry mirror, OpenShift internal registry, managed or bundled PostgreSQL, Redis, MinIO,
and configured model/embedding providers.

## Abuse cases

- Mutable or attacker-controlled probe image executes before privileged initialization Jobs.
- Binary build context unintentionally streams secrets or local artifacts.
- Profile gate accepts a disabled or endpoint-mismatched revision.
- Probe Host workaround bypasses general Django host validation.
- Initialization logs credentials or provider secret values.

## Failure cases

- Helm wait deadlocks before post-install hooks.
- Bootstrap reports success after parsing unexpected shell output.
- Database is reachable but migrations are pending.
- Readiness reports success while database or Redis is unavailable.
- Mirror-only changes make canonical builds unusable elsewhere.

## Logging and audit risks

Database URLs and Secret content must not be printed. Profile creation continues to produce existing
audit events; read-only gate checks do not create audit noise.

## Mitigations

- Digest-pinned probe image schema and examples.
- Explicit, triggerless Binary builds and documented `.dockerignore` boundary.
- Exact active-profile comparison and non-zero mismatch failure.
- Managed pre-hooks versus bundled revisioned Jobs, never post-hook/workload circular waiting.
- HTTP Host and forwarded-scheme headers scoped only to health probes, an already allowlisted
  service hostname and the existing trusted-proxy contract.
- Restricted-SCC security contexts, no API tokens, bounded resources and `/tmp`.

## Residual risks

Namespace administrators and Secret readers retain deployment authority. Registry trust, admission,
quota, CNI, managed-service TLS, backups and live provider behavior require target-environment review.

## Required security tests

- Reject blank/tag-only probe images and unknown values.
- Assert every init/container remains non-root, read-only, tokenless and resource-bounded.
- Assert rendered Helm data contains Secret references, not values.
- Assert disabled/mismatched profiles cannot satisfy the workload gate.
- Assert health probe Host header uses the chart service name and not a route secret or pod IP.
