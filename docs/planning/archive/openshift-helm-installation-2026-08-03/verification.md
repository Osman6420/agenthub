# Verification: OpenShift Helm installation

| Check | Result | Evidence |
| --- | --- | --- |
| Helm 3 lint/render | Pass | Official checksum-verified Helm 3.21.1; strict lint and full render passed. |
| Helm 4 lint/render | Pass | Official checksum-verified Helm 4.2.3; strict lint and full render passed. |
| Chart package | Pass | `agenthub-0.1.0.tgz` packaged successfully in the ignored verification directory. |
| Main render | Pass | 24 YAML documents: six Deployments, two ordered hook Jobs, Services, Routes, release-scoped NetworkPolicies, SAs, ConfigMap and Helm test Pod. |
| Optional demo render | Pass | 30 YAML documents with seventh Deployment, third Route and scoped demo-to-web ingress. |
| Restricted-SCC/resource audit | Pass | Main 9/9 and demo 10/10 workloads/containers: arbitrary non-root UID, read-only root, RuntimeDefault seccomp, no privilege escalation, drop ALL, no service-account token, bounded `/tmp`, CPU/memory/ephemeral request+limit. |
| Hook order | Pass | Migration weight `-10`; bootstrap weight `-5`; both pre-install/pre-upgrade and fail closed. |
| Secret ownership | Pass | No Kubernetes Secret or secret value rendered by Helm; only existing Secret names appear. |
| Closed values schema | Pass | Unknown `provider.model.apiKey`, blank required values, vector dimension 3000, enabled demo without image/host and removed resource limits were rejected. |
| Long release name | Pass | A 53-character Helm release rendered with every resource name at most 63 characters. |
| POSIX shell syntax | Pass | `create-secrets.sh` accepted by container `/bin/sh -n`; LF line endings confirmed. |
| JSON/YAML parse | Pass | Values schema parsed; all rendered Helm documents parsed with PyYAML. |
| Diff hygiene | Pass | `git diff --check` clean at closure. |

## Acceptance mapping

- Application roles are packaged in one chart with immutable application/static image digests and a
  shared release identifier.
- Migration/bootstrap execute before normal workload creation through ordered hooks.
- Credentials remain in externally prepared namespace Secrets and do not enter Helm values/history.
- OpenShift Routes, scoped ingress policies, arbitrary UID and resource constraints are present.
- Generic OpenAI-compatible model and embedding metadata is supplied without Gemini assumptions.
- Ubuntu install, upgrade, rollback, Secret rotation and uninstall boundaries are documented.

## Staff engineering review

Stable selectors exclude release version; resource names are length-bounded; ConfigMap checksums and
an explicit rollout nonce drive safe restarts. The chart has no dependency and packages cleanly.
Migration/bootstrap scripts retain idempotent catalog behavior.

## Application-security review

The values schema is a closed allowlist to prevent ignored secret-like fields from being retained in
Helm release metadata. Secret preparation uses protected files, no tracing/output, dedicated
server-side field ownership and cleanup. Pods receive no Kubernetes API token or RBAC role.

## SRE review

Every container has requests/limits and bounded writable storage; web/static use rolling updates,
beat remains single-replica Recreate, probes and Helm test are present, and failed hooks remain for
diagnosis. Rollback explicitly excludes database reversal and uninstall retains managed data and
external Secrets.

## Checks not run

No target OpenShift cluster is available from this workstation. Server-side dry-run/admission, SCC
mutation, actual hook execution, quota/LimitRange, CNI, Route/TLS, registry pull and managed-service
connectivity remain target-environment checks. ShellCheck was not available; POSIX parsing and manual
review were completed. No Python/frontend behavior changed, so application test suites were not
rerun for this chart-only change.

## Remaining risks

- Default resources require target load testing and quota review.
- External Secret readers retain provider/infrastructure authority; namespace RBAC remains a
  platform responsibility.
- Registry pull credentials, custom CA, proxy/service mesh and exact ingress labels are cluster
  specific.
- Helm rollback does not reverse successful Django migrations.
- Private/RFC1918 provider endpoints remain blocked by the current shared SSRF policy without a
  separately reviewed private-egress implementation.

## Final status

Offline verified on 2026-08-03; do not claim a live OpenShift installation until the target-cluster
acceptance commands in the operator guide pass.
