# Threat Model: OpenShift Ubuntu installation path

## Assets

Database and object data, Django signing key, model/embedding API keys, storage credentials,
consumer bearer tokens, operator credentials, immutable image provenance and audit history.

## Primary threats and controls

| Threat | Control |
| --- | --- |
| Root/privileged container escape | Restricted SCC compatible pod/container security contexts; no fixed UID, privilege escalation or added capabilities. |
| Resource exhaustion or quota rejection | CPU, memory and ephemeral-storage request/limit on every container and Job; bounded `/tmp`. |
| Secret disclosure in Git, argv or logs | Secrets entered through protected temporary env files, applied as Secret objects, no `set -x`, no plaintext manifest. |
| Mutable/supply-chain image | Installer accepts only digest-pinned application/static/demo image references. |
| Open proxy or browser token disclosure | Demo uses a fixed startup-time internal upstream and narrow path allowlist; tokens stay in a mounted Secret file. |
| SSRF/provider destination injection | Model/embedding destinations remain platform-managed immutable HTTPS profiles and existing SSRF-safe egress transport. |
| Over-broad Kubernetes authority | Namespace-scoped objects only; automounted service-account tokens disabled; no Role/ClusterRole. |
| Cross-tenant or cross-consumer access | Existing server-side responsibilities, bindings, grants, signed context and PostgreSQL RLS remain unchanged. |
| Network outage caused by guessed policy | Installer applies scoped ingress policy only; environment-specific default-deny egress is a reviewed explicit step with exact destinations. |
| Destructive reinstall | No namespace, database, PVC or Secret deletion in the normal installer; uninstall is manual and explicitly destructive. |

## Residual risks

The OpenShift administrator must validate registry trust, cluster ingress labels, managed-service TLS,
DNS/proxy behavior, egress destinations, backup/restore and quota sizing. Anyone able to read the
namespace Secrets can use external-provider and consumer credentials; namespace RBAC remains a
platform responsibility.
