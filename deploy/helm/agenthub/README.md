# AgentHub OpenShift Helm chart

This chart is the preferred packaged installation path for OpenShift. It deploys AgentHub with
restricted-SCC-compatible security contexts, mandatory resource bounds, immutable image digests,
ordered database initialization, fail-closed workload gates, Routes and scoped ingress
NetworkPolicies.

The chart deliberately does **not** accept credential values. Helm stores supplied values in release
metadata, so database, Redis, object-store, model and embedding credentials must exist in
namespace-scoped Secrets before `helm upgrade --install`.

## 1. Prerequisites

- an authenticated `oc` session and an existing target namespace;
- Helm 3 or 4 compatible with the target Kubernetes/OpenShift version;
- application, static and PostgreSQL-client probe images pushed and resolved to `sha256` digests;
- managed PostgreSQL with pgvector, Redis and S3-compatible storage;
- OpenAI-compatible chat-completions and embedding HTTPS endpoints.

## 2. Create protected Secrets

Use the same protected environment contract as the direct installer:

```sh
cp deploy/openshift/install/openshift.env.example openshift.env
chmod 600 openshift.env
vi openshift.env

chmod +x deploy/helm/agenthub/scripts/create-secrets.sh
./deploy/helm/agenthub/scripts/create-secrets.sh ./openshift.env
```

The helper uses `NAMESPACE` from `openshift.env`, creates six split Secrets with a dedicated
server-side-apply field manager, never enables shell tracing, never prints values, and removes
protected temporary files on exit. It is authoritative for the data keys in those six named
Secrets. If Secret names are overridden in Helm values, create those Secrets through the platform's
approved secret-management workflow instead of this default-name helper.

## 3. Prepare non-secret values

```sh
cp deploy/helm/agenthub/values.openshift.example.yaml agenthub-values.yaml
vi agenthub-values.yaml
```

Replace the all-zero image digests, registry repositories, Route host, object-store settings, model
host/path/name and embedding host/path/name/dimension. Never add API keys, passwords, database URLs
or consumer tokens to this file or pass them with `--set`.

Keep `databaseInitialization.mode: hooks` for this managed-service chart. Its digest-pinned probe
image must contain `pg_isready`. The bundled chart sets `mode: jobs` because its PostgreSQL resource
is created by the same Helm release.

`objectStore.allowInsecureHttp` remains `false` for this primary chart. The separate bundled
non-production stack is the only documented path that sets it to `true` for namespace-internal
MinIO; do not use that exception with an external endpoint or production data.

## 4. Render and validate

```sh
helm lint deploy/helm/agenthub -f agenthub-values.yaml --strict

helm template agenthub deploy/helm/agenthub \
  --namespace agenthub-demo \
  -f agenthub-values.yaml \
  | oc apply --namespace agenthub-demo --dry-run=server -f -
```

Do not bypass an SCC, quota, Route, schema or admission failure with validation-disable flags.

## 5. Install

```sh
helm upgrade --install agenthub deploy/helm/agenthub \
  --namespace agenthub-demo \
  -f agenthub-values.yaml \
  --atomic \
  --wait \
  --wait-for-jobs \
  --timeout 20m
```

The pre-install hooks wait for PostgreSQL, run migration first and bootstrap second. Bootstrap
creates missing profiles or rejects an existing disabled/mismatched immutable revision. Every
application workload also performs a read-only migration/profile gate before starting. A hook
failure blocks workload creation and leaves the failed Job available for diagnosis. Successful hook
Jobs are removed.

```sh
helm status agenthub --namespace agenthub-demo
oc get pods,routes --namespace agenthub-demo
helm test agenthub --namespace agenthub-demo --logs
```

After a successful first install, delete only the one-time bootstrap password Secret. The hook makes
that Secret optional on later upgrades and needs it again only if the recovery actor does not exist.

```sh
oc delete secret agenthub-bootstrap-credentials --namespace agenthub-demo
```

## 6. Upgrade

Build and push application/static images with one new `releaseId`, put their new digests in the
values file, then run the same `helm upgrade --install` command. Migration/bootstrap hooks run before
the Deployment rollout. If external Secret values changed, rerun the Secret helper and change
`rolloutNonce` to a new non-secret value so every Deployment restarts.

## 7. Rollback and uninstall

```sh
helm history agenthub --namespace agenthub-demo
helm rollback agenthub PREVIOUS_REVISION --namespace agenthub-demo --wait --timeout 20m
```

Helm rollback restores manifests and images; it does not reverse database migrations. Review schema
compatibility before rollback.

```sh
helm uninstall agenthub --namespace agenthub-demo
```

Uninstall intentionally leaves external Secrets and managed PostgreSQL/Redis/object-store data.
Delete them only through a separately approved cleanup procedure.

## Optional external demo

The demo is disabled by default. Enabling it requires an immutable demo image, a separate Route host
and an existing Secret containing key `credentials.json`. The chart never accepts or creates demo
tokens. If a token-entry-only static page is adopted later, keep it as a separate reviewed delivery
change rather than weakening AgentHub CORS or embedding credentials in JavaScript.
