# Threat model: OpenShift Helm installation

## Assets

- Database, Redis, object-store and provider credentials.
- Bootstrap recovery password and platform profile authority.
- Immutable application/static/demo image identity.
- Tenant documents, prompts, embeddings, releases and consumer tokens.
- Namespace deployment and Route integrity.

## Threats and controls

| Threat | Control |
| --- | --- |
| Secrets leak through Helm values/history | Chart accepts existing Secret names only; the POSIX helper creates namespace Secrets separately and disables tracing. |
| Shell injection from config | Environment file is explicitly a trusted operator input; helper validates names/newlines and never evaluates generated values as commands. |
| Root/privileged execution | No fixed UID; `runAsNonRoot`, RuntimeDefault seccomp, read-only root, drop ALL, no privilege escalation. |
| Kubernetes API credential theft | Workload and hook pods set `automountServiceAccountToken: false`; no RBAC role is created. |
| Unbounded resource consumption | Every container has CPU, memory and ephemeral-storage requests/limits; writable `/tmp` is size-bounded. |
| Mutable or mismatched images | Image digests are schema/template-required; application and static share one release identifier. |
| Workloads start before migration | Ordered pre-install/pre-upgrade migration and bootstrap hook Jobs block normal resource rollout. |
| Cross-release NetworkPolicy impact | Selectors include the Helm release instance label. |
| Unsafe automated rollback | Documentation states that Helm rollback does not reverse database migrations. |
| Demo token exposure | Optional demo requires an externally created credential Secret mounted read-only; the chart never accepts token values. |

## Residual risks

Target administrators must validate registry trust, ingress namespace labels, quota, CNI behavior,
outbound destinations, managed-service TLS/custom CA, backups and provider compatibility. Anyone
with namespace Secret read access can use infrastructure/provider credentials; namespace RBAC is a
platform responsibility.
