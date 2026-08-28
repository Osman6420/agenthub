# ADR 0018: Portable OpenShift build and database initialization

- **Status:** Accepted
- **Date:** 2026-08-28

## Context

AgentHub supports a production-oriented Helm chart backed by already-managed services and a
non-production bundled chart that creates PostgreSQL, Redis and MinIO in the same release. A
restricted OpenShift environment exposed three portability gaps: build nodes required an approved
registry mirror and Binary source, the builder could not select the static target from a multi-stage
Dockerfile, and bundled database initialization could not use pre-install hooks because PostgreSQL
did not exist yet. Moving initialization to post-install recovered a live deployment only when Helm
wait semantics were disabled, because application init containers waited on post-install work while
Helm waited for those applications to become ready.

## Decision drivers

- Preserve `--atomic --wait --wait-for-jobs` and fail-closed rollout behavior.
- Keep managed-service installs blocking before normal resource creation.
- Avoid hard-coding one organization's registry, namespace, release or image digest.
- Preserve semantic readiness and restricted-SCC/least-privilege controls.
- Reject stale, disabled or configuration-mismatched immutable provider profiles.

## Considered options

1. Use post-install hooks and document that operators must omit `--wait` and `--atomic`.
2. Use one hook strategy for both external and bundled databases.
3. Split infrastructure and application into separate releases in every environment.
4. Keep managed-database pre-hooks and use Helm-managed revisioned Jobs for the bundled release.

## Decision

The application chart exposes two closed database-initialization modes. `hooks` is the default for
managed/external databases and retains ordered `pre-install,pre-upgrade` migration/bootstrap hooks.
`jobs` is selected by the bundled chart and renders revision-named, Helm-managed normal Jobs. The
migration Job waits for PostgreSQL; the bootstrap Job waits for migrations; all application roles
perform a read-only migration and exact active-profile gate before starting.

Bootstrap uses one idempotent management command instead of parsing `manage.py shell` stdout. It
creates missing profiles through the existing platform-admin services and fails if an existing
immutable revision differs from declared fields or is disabled. Read-only gates distinguish
transient missing/database state from fatal configuration mismatch.

All probe/helper images are repository-plus-digest values. HTTP startup/liveness/readiness probes
connect to the pod IP but send an allowlisted Service hostname and the trusted ingress scheme in
`Host`/`X-Forwarded-Proto` headers; readiness keeps the semantic `/v1/health/ready` endpoint without
an internal HTTPS redirect to the plaintext container port.

Canonical Dockerfiles retain upstream defaults through build arguments. A triggerless OpenShift
Binary Build template supplies organization mirror references and one release identifier. A
standalone static Dockerfile is maintained for builders that cannot select a multi-stage target.

## Security consequences

Probe images become explicit digest-pinned executable inputs. Init/workload containers remain
non-root, read-only, capability-free, tokenless and resource-bounded. Database passwords are not
placed in probe process arguments. Exact profile comparison prevents a disabled or stale endpoint
revision from silently satisfying rollout. The health-probe Host header uses a hostname already in
`DJANGO_ALLOWED_HOSTS`; general host validation is not weakened.

## Operational consequences

Managed and bundled charts have intentionally different initialization lifecycles. Bundled installs
must keep `--wait-for-jobs`. Completed revisioned Jobs are release-managed evidence. Binary builds
must be started explicitly with streamed source and cannot use automatic triggers. Target operators
must provide and promote a PostgreSQL-client image containing `pg_isready`.

## Data and privacy consequences

No schema, tenant data or Secret-storage behavior changes. Missing platform profiles may be created;
existing immutable profiles are not rewritten. Logs contain readiness reason codes/field names, not
credentials or profile secret values.

## Positive consequences

- Bundled installs retain Helm atomic/wait safety without a lifecycle deadlock.
- Managed installs preserve their proven pre-hook ordering.
- Mirror-only clusters no longer force private registry addresses into canonical Dockerfiles.
- Readiness continues to remove dependency-unhealthy pods from Service backends.

## Negative consequences

- The chart has an additional required digest-pinned image input.
- Two initialization modes require render tests and operator documentation.
- The standalone static Dockerfile duplicates a bounded build sequence and needs parity tests.
- Revisioned bundled Jobs add release objects until Helm replaces the prior revision.

## Migration impact

No Django migration. Existing environment values must add `databaseInitialization` and non-secret
database connection components to the generated runtime/migration Secrets. Bundled values select
`jobs`; managed values select `hooks`.

## Rollback considerations

Rolling chart templates back does not undo successful migrations or created immutable profiles.
Before rollback, confirm schema compatibility and restore the matching application/static digests,
release identifier and initialization values. Do not reintroduce post-install database hooks with
workload gates.

## References

- [`openshift-deploy-portability-hardening`](../planning/archive/openshift-deploy-portability-hardening-2026-08-28/plan.md)
- [`openshift-helm-installation`](../operations/openshift-helm-installation.md)
- [`openshift-bundled-stack-helm`](../operations/openshift-bundled-stack-helm.md)
