# Verification: OpenShift bundled stack Helm chart

Date: 2026-08-03

## Passed evidence

- Helm 3.21.1 and Helm 4.2.3 strict lint passed for `agenthub-stack`; the child `agenthub` chart also
  passed Helm 3 strict lint.
- `helm dependency build` regenerated the local dependency lock/package and Helm 3 packaged
  `agenthub-stack-0.1.0.tgz` successfully.
- Rendered invariant check parsed 37 documents: 13 workloads, three StatefulSets/PVC templates,
  six NetworkPolicies, three dependency Services, zero rendered Secrets and three ordered hooks.
- Every rendered container/init container has CPU, memory and ephemeral-storage requests/limits,
  non-root/read-only/no-escalation/drop-ALL security settings; every pod disables token automount and
  uses `RuntimeDefault` seccomp. No fixed `runAsUser` was rendered.
- Negative schema checks rejected an invalid digest, unknown password field, missing resource bound
  and invalid PVC size.
- Linux `sh -n` passed for the image entrypoint, Secret helper, rendered PostgreSQL init script and
  rendered MinIO bucket hook.
- The pgvector image built from `deploy/postgres-openshift.Dockerfile` and ran under UID 12345 with a
  read-only root filesystem and only the chart-declared writable paths. PostgreSQL became ready and
  `CREATE EXTENSION vector` succeeded.
- The rendered database initialization ran under UID 23456. It created the database, vector
  extension and separate migration/application roles; both roles were verified non-superuser,
  non-createdb, non-createrole, noinherit and non-bypass-RLS.
- Representative locally cached Redis 7.4.9 and MinIO RELEASE.2025-09-07 images ran under UIDs 34567
  and 34568 with read-only root filesystems; Redis returned PONG and MinIO readiness succeeded. Redis
  PVC permissions were tested with a group-writable volume matching the OpenShift fsGroup contract.
- `git diff --check` passed. Secret values were not printed or added to Helm values/templates.

## Not run

- No target OpenShift server-side dry-run or install: no authenticated cluster was available.
- No registry push/pull, storage-class provisioning, Route/router, quota/LimitRange, SCC admission,
  NetworkPolicy data-plane or persistent backup/restore drill.
- The user-supplied immutable Redis, MinIO and `mc` image versions still require the same target-image
  smoke/admission checks; local representative images are not provenance evidence for those images.

## Cleanup

All temporary PostgreSQL, Redis and MinIO verification containers were removed after the checks.
