# AgentHub installation on OpenShift with Helm

This is the primary packaged installation path after images have been built and pushed. The chart is
located at `deploy/helm/agenthub`. It uses OpenShift Routes and Kubernetes namespace resources; it
does not install or modify an SCC, cluster role, managed database, Redis, object store or registry.

## Installation sequence

### 1. Log in and select the namespace

```sh
oc login --server='https://api.cluster.example.com:6443' --token='REPLACE'
oc new-project agenthub-demo       # only when authorized and the project does not exist
oc project agenthub-demo
```

### 2. Build, push and resolve immutable images

```sh
export RELEASE_ID=release-20260803-1
export REGISTRY=registry.example.com/team

docker build --target application \
  --build-arg STATIC_RELEASE_ID="$RELEASE_ID" \
  -t "$REGISTRY/agenthub:$RELEASE_ID" -f deploy/Dockerfile .

docker build --target static-runtime \
  --build-arg STATIC_RELEASE_ID="$RELEASE_ID" \
  -t "$REGISTRY/agenthub-static:$RELEASE_ID" -f deploy/Dockerfile .

docker push "$REGISTRY/agenthub:$RELEASE_ID"
docker push "$REGISTRY/agenthub-static:$RELEASE_ID"

skopeo inspect --format '{{.Digest}}' "docker://$REGISTRY/agenthub:$RELEASE_ID"
skopeo inspect --format '{{.Digest}}' "docker://$REGISTRY/agenthub-static:$RELEASE_ID"
```

Use the resulting repository and digest as separate `images.*.repository` and `images.*.digest`
values. Application and static images must use the same release ID.

### 3. Prepare the protected environment file

```sh
cp deploy/openshift/install/openshift.env.example openshift.env
chmod 600 openshift.env
vi openshift.env
```

Fill the namespace, runtime/migration database URLs and their matching non-secret host/port/name/user
components, Redis URL, object-store credentials,
`DJANGO_SECRET_KEY`, metrics token, bootstrap password, model API key and embedding API key. The
provider host/path/name and image/Route fields in this file are used by the direct installer; Helm
uses the corresponding non-secret fields from `agenthub-values.yaml`.

The initial console login is the `PLATFORM_ACTOR` username and `BOOTSTRAP_ADMIN_PASSWORD` value on a
fresh database. Existing recovery actors are never silently password-rotated.

### 4. Create external Secrets

```sh
chmod +x deploy/helm/agenthub/scripts/create-secrets.sh
./deploy/helm/agenthub/scripts/create-secrets.sh ./openshift.env
```

Confirm only names, never values:

```sh
oc get secret -n agenthub-demo \
  agenthub-web-secrets agenthub-runtime-secrets agenthub-ingestion-secrets \
  agenthub-beat-secrets agenthub-migration-secrets agenthub-bootstrap-credentials
```

### 5. Prepare non-secret Helm values

```sh
cp deploy/helm/agenthub/values.openshift.example.yaml agenthub-values.yaml
vi agenthub-values.yaml
```

Replace every example host/name and all-zero digest. Model and embedding endpoints are generic
OpenAI-compatible HTTPS endpoints. `provider.*.host` contains no scheme; paths begin with `/`.
Embedding dimensions must match stored geometry: `vector` supports up to 2,000 and `halfvec` up to
4,000. Do not put credentials in the Helm values file: Helm release storage would retain them.

Keep `databaseInitialization.mode: hooks`. Set `probeImage` to an approved, digest-pinned image that
contains `pg_isready`; the init container receives only non-secret database connection components,
not a password in its command line.

For private registries, create an approved namespace pull Secret and set only its name:

```yaml
imagePullSecrets:
  - name: approved-registry-pull-secret
```

### 6. Preflight

```sh
helm lint deploy/helm/agenthub -f agenthub-values.yaml --strict

helm template agenthub deploy/helm/agenthub \
  --namespace agenthub-demo -f agenthub-values.yaml \
  | oc apply --namespace agenthub-demo --dry-run=server -f -
```

The server-side dry run is the target-cluster check for Route APIs, restricted SCC mutation, quota,
LimitRange and policy admission. Never solve failures with root, `anyuid`, privileged SCC, removed
limits, writable root filesystem or disabled validation.

### 7. Install

```sh
helm upgrade --install agenthub deploy/helm/agenthub \
  --namespace agenthub-demo \
  -f agenthub-values.yaml \
  --atomic --wait --wait-for-jobs --timeout 20m
```

Hook order is deterministic: migration weight `-10`, bootstrap weight `-5`, then normal resources.
Both hooks wait for PostgreSQL. Bootstrap creates missing profiles through the platform-admin service
or rejects a disabled/configuration-mismatched existing revision. Workloads independently gate on
applied migrations and those exact active profiles. Hooks do not mount service-account tokens. A
failed hook blocks the release and remains available:

```sh
oc get jobs -n agenthub-demo
oc logs -n agenthub-demo job/agenthub-migrate --tail=200
oc logs -n agenthub-demo job/agenthub-bootstrap --tail=200
```

### 8. Verify and log in

```sh
helm status agenthub -n agenthub-demo
oc get pods,deploy,routes -n agenthub-demo
helm test agenthub -n agenthub-demo --logs
curl --fail --show-error "https://YOUR_ROUTE_HOST/v1/health/ready"

oc exec -n agenthub-demo deployment/agenthub-web -- id
oc exec -n agenthub-demo deployment/agenthub-web -- \
  sh -c 'test "$(id -u)" -ne 0 && test ! -w /app && test -w /tmp'
```

Open `https://YOUR_ROUTE_HOST/console/`. On a fresh database, use the configured `PLATFORM_ACTOR`
and `BOOTSTRAP_ADMIN_PASSWORD`. Then remove the one-time Secret:

```sh
oc delete secret agenthub-bootstrap-credentials -n agenthub-demo
```

### 9. Upgrade and Secret rotation

Use a new immutable release ID and application/static digests. If credentials rotate, update the
external Secrets with the helper and change `rolloutNonce` in values. Run the same
`helm upgrade --install` command. Hooks migrate/bootstrap before rollout.

### 10. Rollback

```sh
helm history agenthub -n agenthub-demo
helm rollback agenthub PREVIOUS_REVISION -n agenthub-demo --wait --timeout 20m
```

Rollback does not reverse Django migrations. Validate database compatibility and backups before
rolling application images backward.

### 11. Uninstall boundary

```sh
helm uninstall agenthub -n agenthub-demo
```

External Secrets and managed data are deliberately retained. Namespace/database/bucket deletion is
not part of Helm uninstall.

## Operational notes

- The chart creates no Kubernetes Role or RoleBinding because workloads never call the API.
- All pods use OpenShift-assigned arbitrary UIDs and bounded `/tmp` volumes.
- A release-scoped ConfigMap checksum and `rolloutNonce` control deterministic rollout.
- Environment-specific egress is not guessed. Provider, database, Redis and object-store
  destinations must be approved by the platform team.
- The current shared provider transport rejects private/RFC1918 endpoint resolution. A private model
  gateway needs a reviewed private-egress implementation; do not disable SSRF or TLS controls.
