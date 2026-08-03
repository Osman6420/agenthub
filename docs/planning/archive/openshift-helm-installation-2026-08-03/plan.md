# Task Plan: OpenShift Helm installation

## Task summary

Add a production-oriented Helm chart for installing AgentHub on OpenShift from Ubuntu while
preserving the existing restricted-SCC, arbitrary-UID, immutable-image, resource-bound and
provider-neutral deployment contract.

## Scope

- Package web, static, runtime, ingestion, evaluation and beat roles in one Helm chart.
- Run migration and bootstrap as ordered pre-install/pre-upgrade Helm hook Jobs.
- Keep provider and infrastructure credentials in pre-created namespace Secrets rather than Helm
  values or Helm release storage.
- Add a POSIX `sh` helper that converts the protected installer environment file into the required
  namespace Secrets without printing their values.
- Support OpenShift Routes, scoped ingress NetworkPolicies and an optional separately credentialed
  external-demo workload.
- Document first install, verification, upgrade, rollback and uninstall from Ubuntu.

## Non-goals

- No bundled PostgreSQL, Redis, object storage, registry or model provider.
- No cluster-scoped RBAC, SCC mutation, fixed UID, root or privileged workload.
- No automatic provider credential storage in `values.yaml` or `--set` arguments.
- No automatic database rollback, namespace deletion or Secret deletion on uninstall.
- No automatic external-demo credential seeding from inside a pod with Kubernetes API privileges.

## Trust boundaries and data flows

- Ubuntu operator -> OpenShift API via authenticated `oc` and Helm clients.
- Secret preparation helper -> namespace Secrets via `oc create --dry-run=client | oc apply`.
- Helm release metadata -> non-secret deployment configuration only.
- Migration/bootstrap hooks -> managed PostgreSQL and immutable platform profile catalogs.
- Application roles -> managed PostgreSQL, Redis, object storage and approved model endpoints.
- OpenShift ingress controller -> TLS Routes -> web/static/optional demo Services.

## Security and authorization impact

The chart creates only namespace-scoped workload resources and requests no Kubernetes API access
from application pods. Every container is non-root, uses a read-only root filesystem, drops all
capabilities, denies privilege escalation, uses RuntimeDefault seccomp, and has CPU, memory and
ephemeral-storage requests and limits. Existing application authorization, tenant isolation and
platform profile responsibilities remain authoritative.

## Operational risks

- Pre-install/pre-upgrade hooks make a failed migration or bootstrap block the Helm release, by
  design; failed hook Jobs remain available for diagnosis.
- External Secrets are intentionally not owned by Helm and therefore require explicit rotation and
  cleanup procedures.
- Registry pull credentials, Routes, custom CAs, proxy/service mesh and egress are cluster-specific.
- Helm rollback cannot reverse a database migration and must use migration-specific review.

## Implementation steps

1. Define values/schema/helpers and stable naming/label contracts.
2. Implement ConfigMap, service accounts, workloads, Services, Routes and NetworkPolicies.
3. Implement ordered migration/bootstrap hooks without mounted service-account tokens.
4. Add protected Secret preparation and provider-neutral example values.
5. Add Ubuntu/OpenShift Helm operator guide and update deployment documentation indexes.
6. Run Helm lint/template, YAML/schema, shell, security-invariant and final-diff checks.
7. Record verification and archive only after implemented and verified evidence is complete.

## Rollback

Use `helm rollback` only for application/static image and configuration rollback after reviewing the
schema state. Never assume it reverses Django migrations. External Secrets and managed data remain
outside Helm ownership and are not removed automatically.

## Status

Implemented and offline verified on 2026-08-03. Target-cluster server-side admission, Route, SCC,
CNI, registry and managed-service connectivity remain environment acceptance gates.
