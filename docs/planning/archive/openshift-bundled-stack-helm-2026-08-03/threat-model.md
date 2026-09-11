# Threat model: OpenShift bundled stack Helm chart

## Assets and boundaries

- PostgreSQL data and administrative/migration/runtime credentials.
- Redis state/password and MinIO objects/root plus bucket-scoped application credentials.
- Application/provider credentials, tenant data, bootstrap authority, PVCs and immutable images.
- Ubuntu operator to OpenShift API, Secret to pod, and pod to dependency trust boundaries.

## Threats and controls

| Threat | Control |
| --- | --- |
| Credentials retained in Helm history | Closed values schemas accept Secret names only; helper creates Secrets outside Helm. |
| Database runtime privilege escalation | Separate admin, schema-owner/migrator and `NOSUPERUSER NOBYPASSRLS` runtime roles. |
| Root/fixed UID requirement | pgvector image supports NSS lookup for arbitrary UID; pods omit `runAsUser` and use restricted contexts. |
| Dependency exposed externally | PostgreSQL, Redis and MinIO have ClusterIP Services only and release-scoped ingress policies. |
| Cross-release traffic | Dependency and allowed-client selectors include the Helm instance label. |
| Application receives MinIO administrative access | Bootstrap retains root credentials and creates a distinct identity limited to the configured bucket. |
| Unbounded resource/storage use | Closed schemas require resource bounds and PVC sizes; writable ephemeral paths are bounded. |
| Destructive uninstall | StatefulSet retention policies preserve PVCs and external Secrets are not Helm-owned. |
| False production confidence | Chart/docs label the topology non-production and enumerate HA/TLS/backup gaps. |

## Residual risks

Namespace administrators and Secret readers control the data-plane credentials. Internal dependency
traffic is plaintext. Storage durability, backup/restore, image provenance, stateful upgrades and
admission behavior require target-platform review.
