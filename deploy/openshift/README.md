# Sprint 7 OpenShift Drafts

These manifests are reviewable deployment drafts, not evidence of a live deployment.
Render and policy-test them in CI, then tailor namespaces, image digests, storage,
resource sizing, routes, approved egress destinations, and platform labels before use.

Security invariants:

- only `agenthub-web` has a `Route`;
- MCP is disabled in the base ConfigMap and must be enabled only by an approved
  internal/VPN environment overlay;
- the metrics endpoint requires a secret-backed scrape bearer token even on the
  private network;
- runtime, ingestion, eval, beat, migration, databases, Redis, object storage, metrics,
  and tracing endpoints have no external ingress;
- namespace traffic is default-deny and workload service accounts are distinct;
- secrets enter through logical External Secret references, never plaintext manifests;
- the container image must be pinned by digest in an environment overlay.

`platform.yaml` intentionally uses placeholder dependency services and external-secret
store names. A platform/SRE reviewer must replace them with approved environment values.
