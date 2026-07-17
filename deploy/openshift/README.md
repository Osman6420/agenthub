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

The reviewed Python-node runner is a separate four-replica, internal-only Deployment. It uses the
dedicated `deploy/python-runner.Dockerfile`, receives no application ConfigMap or Secret, has no
service-account token or DNS/egress policy, and accepts traffic only from the runtime worker. Each
pod admits one execution at a time and starts a fresh child process. The supervisor exits after 20
executions or 15 minutes so OpenShift restarts a clean container; the application has no permission
to create or delete pods.

The base manifest does **not** activate Python nodes. An environment overlay may set
`PYTHON_NODE_RUNTIME_ENABLED`, the resolver/runner adapter, internal runner URL and
`PYTHON_NODE_RUNNER_ATTESTED` only after the exact rendered workload passes ADR-0011 restricted-v2,
RuntimeDefault seccomp, default-deny network, resource/recycle and service-mesh mTLS probes. A plain
HTTP cluster Service without authenticated encrypted transport is not attested production evidence.

`platform.yaml` intentionally uses placeholder dependency services and external-secret
store names. A platform/SRE reviewer must replace them with approved environment values.
