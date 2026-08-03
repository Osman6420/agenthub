# Archived task: OpenShift bundled stack Helm chart

## Outcome

Implemented and offline verified a separate all-in-one Helm chart that installs AgentHub plus
single-replica PostgreSQL/pgvector, Redis and MinIO in one OpenShift namespace for demonstrations
and controlled non-production environments.

## Delivered scope

- Local `agenthub` chart dependency plus three release-scoped StatefulSets, Services and retained
  PVC templates.
- Restricted-SCC-safe workload settings: arbitrary UID, non-root, read-only root filesystem,
  `RuntimeDefault` seccomp, no service-account token, dropped capabilities and complete resource
  requests/limits.
- Arbitrary-UID-compatible pgvector image and first-initialization script with separate admin,
  migration and runtime roles.
- External Secret helper for PostgreSQL, Redis, MinIO, AgentHub and generic OpenAI-compatible LLM
  and embedding credentials.
- MinIO bucket bootstrap with a distinct bucket-scoped AgentHub identity.
- Release-scoped dependency ingress policies and no dependency Routes.
- Ubuntu/OpenShift build, preflight, install, verification, rotation, rollback and data-retention
  guide.

## Explicit boundary

This is not a production/HA topology. Dependencies are single replica; namespace-internal database,
Redis and MinIO connections are not TLS protected; backups and restores are platform work. The
primary `agenthub` chart with approved managed services remains the production path.

## Verification

See [verification.md](verification.md). No live OpenShift cluster was available, so target-cluster
admission, storage, Route, quota and network connectivity remain required gates.
