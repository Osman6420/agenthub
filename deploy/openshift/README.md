# Sprint 7 OpenShift Drafts

For the preferred packaged Helm path, see
[`docs/operations/openshift-helm-installation.md`](../../docs/operations/openshift-helm-installation.md)
and [`deploy/helm/agenthub`](../helm/agenthub/). For a self-contained, non-production demo with
PostgreSQL/pgvector, Redis and MinIO in the same namespace, see
[`docs/operations/openshift-bundled-stack-helm.md`](../../docs/operations/openshift-bundled-stack-helm.md)
and [`deploy/helm/agenthub-stack`](../helm/agenthub-stack/). For the lower-level Ubuntu/`oc` installation path,
restricted-SCC templates, generic OpenAI-compatible model/embedding configuration and optional
external-consumer showcase, see
[`docs/operations/openshift-ubuntu-installation.md`](../../docs/operations/openshift-ubuntu-installation.md)
and [`deploy/openshift/install`](install/). The older `platform.yaml` in this directory remains a
reviewable base draft; do not mix the two paths in one rollout.

These manifests are reviewable deployment drafts, not evidence of a live deployment.
Render and policy-test them in CI, then tailor namespaces, image digests, storage,
resource sizing, routes, approved egress destinations, and platform labels before use.

Clusters that accept only Binary BuildConfig sources can render the triggerless, parameterized
OpenShift Template in [`build/template.yaml`](build/template.yaml). Supply one release ID and the
four organization-approved base-image references, apply the rendered ImageStreams/BuildConfigs,
then explicitly stream the repository with `oc start-build --from-dir=.`. Binary builds have no
automatic trigger because their source exists only in the operator-uploaded stream. Canonical
Dockerfiles retain upstream defaults; mirror references belong in these build parameters.

Security invariants:

- only `agenthub-web` and the public, content-free `agenthub-static` workload have Routes;
- environment overlays replace the shared `.invalid` Route hostname, application/static image
  placeholders and static release id together; both images are pinned by digest;
- `/static` uses the exact same host as the web Route and targets only `agenthub-static`;
- the static workload runs the owner-approved non-root Nginx image target, has no service-account
  token or egress, mounts only a bounded ephemeral `/tmp`, and serves collected application assets;
- MCP is disabled in the base ConfigMap and must be enabled only by an approved
  internal/VPN environment overlay;
- the metrics endpoint requires a secret-backed scrape bearer token even on the
  private network;
- runtime, ingestion, eval, beat, migration, databases, Redis, object storage, metrics,
  and tracing endpoints have no external ingress;
- namespace traffic is default-deny and workload service accounts are distinct;
- secrets enter through logical External Secret references, never plaintext manifests;
- the container image must be pinned by digest in an environment overlay.

## Application and static image promotion

Build both targets from the same commit and release id:

```bash
docker build --target application -t <registry>/agenthub:<release-id> .
docker build --target static-runtime \
  --build-arg STATIC_RELEASE_ID=<release-id> \
  -t <registry>/agenthub-static:<release-id> .
```

The build runs locked frontend type checking/tests/build, Django `collectstatic` and the
fail-closed static inventory before either target completes. The environment overlay must set:

- the web and static images to their immutable registry digests;
- both Route `spec.host` values to the same approved hostname;
- `AGENTHUB_STATIC_RELEASE_ID=<release-id>`;
- `DJANGO_STATIC_URL=/static/<release-id>/`.

Deploy the static workload and verify `/healthz` and required JS/CSS before rolling the web
workload. Promotion must fail if the two release identifiers differ, a digest is not pinned,
required assets are missing, or JS/CSS content types are wrong.

Rollback restores the previous web and static image digests plus the matching static release id and
URL as one reviewed operation. Retain the previous static image for the environment rollback window;
never delete it during forward rollout.

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
