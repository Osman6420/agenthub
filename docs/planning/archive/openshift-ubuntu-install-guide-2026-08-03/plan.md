# Task Plan: OpenShift Ubuntu installation guide

## Task summary

Provide a reproducible Ubuntu `sh` installation path for AgentHub and its external-consumer demo on
OpenShift, respecting restricted SCC, arbitrary runtime UIDs, mandatory resource requests/limits,
read-only filesystems, secret handling, health gates and immutable images. The operator supplies
generic OpenAI-compatible model and embedding endpoints, model names and API keys; Gemini is not
assumed.

## Scope

- Add OpenShift Templates for the application roles/static service and optional external demo.
- Add an Ubuntu POSIX-shell installer driven by environment variables and `oc`.
- Adapt the standalone demo server for an explicitly configured in-cluster upstream while keeping
  loopback-only defaults.
- Allow the external-demo seeder to reuse pre-registered model/embedding profiles and emit an
  environment-specific API base without persisting provider credentials.
- Document image build/push, external PostgreSQL/Redis/S3 prerequisites, model and embedding profile
  registration, egress, install, verification, upgrade, rollback and uninstall boundaries.
- Add focused tests and static validation evidence.

## Non-goals

- No production cluster access or live deployment from this workstation.
- No bundled PostgreSQL, Redis, MinIO, registry, operator or cluster-wide SCC modification.
- No root container, privileged SCC, fixed `runAsUser`, catch-all RBAC or plaintext secret manifest.
- No automatic destructive namespace/database/PVC deletion.
- No new dependency or public API contract.

## Acceptance criteria

1. Every container and Job has CPU, memory and ephemeral-storage requests/limits.
2. Workloads run non-root under OpenShift-assigned UIDs, drop all capabilities, deny privilege
   escalation, use RuntimeDefault seccomp and mount bounded writable `/tmp` where required.
3. Service-account tokens are not mounted because the workloads do not call the Kubernetes API.
4. Images are required by digest and application/static release identifiers must match.
5. Secrets are created from protected temporary files and are never printed or committed.
6. The installer is Ubuntu/POSIX `sh`, validates inputs/cluster login and waits for migration,
   rollout and health gates.
7. Model and embedding configuration is provider-neutral and uses existing immutable
   OpenAI-compatible profile and environment-secret seams.
8. The optional external demo keeps tokens server-side, uses a narrow in-cluster upstream and is
   reachable through a TLS Route.
9. Documentation clearly identifies environment-specific egress/network-policy and managed-service
   decisions that cannot be safely guessed by the installer.

## Trust boundaries and data flows

- Ubuntu operator shell -> OpenShift API through the authenticated `oc` session.
- OpenShift Route -> web/static/demo services.
- Application roles -> PostgreSQL, Redis and S3-compatible object storage.
- Web/runtime/eval -> operator-approved model HTTPS endpoint.
- Ingestion -> operator-approved embedding HTTPS endpoint and approved document sources.
- External demo -> internal AgentHub Service with server-side consumer bearer tokens.

## Security and authorization impact

The installer creates namespace-scoped workload identities, Secrets, workloads, Services, Routes
and ingress NetworkPolicies. It requests no cluster role and never changes SCC configuration. Model
and embedding profiles remain platform-admin-only, immutable catalog records. Existing tenant,
consumer, scenario and document grants remain authoritative.

## Operational risks

- External managed-service URLs, certificates, DNS, proxies and egress controls are cluster-specific.
- A wrong embedding dimension makes indexing fail closed and requires a new profile/reindex.
- Applying default-deny egress without exact environment policies can make the application
  unavailable; the generic installer therefore documents and validates this as a separate reviewed
  overlay rather than guessing CIDRs.
- Route/static release mismatch intentionally prevents startup or breaks static delivery.
- Failed migrations block rollout; rollback must not reverse a destructive migration automatically.

## Implementation steps

1. Inspect current production settings, images, OpenShift drafts, provider registration commands and
   demo runtime.
2. Add restricted-SCC-safe templates and installer with fail-closed input validation.
3. Add generic provider/profile and cluster-demo seams with compatibility tests.
4. Add the operator guide and update current-state indexes.
5. Validate YAML/template structure, POSIX shell syntax, Python tests/static checks and final diff.
6. Record verification, update the master plan and archive the completed task only after evidence.

## Rollback

Reapply the previous immutable image digests and matching static release identifier. Scale down or
delete only the namespace-scoped demo resources explicitly named by the guide. Database rollback is
never automatic; preserve managed-service backups and follow migration-specific review.

## Status

Implemented and offline/container verified on 2026-08-03. Target-cluster admission and connectivity
remain explicit environment acceptance gates.
