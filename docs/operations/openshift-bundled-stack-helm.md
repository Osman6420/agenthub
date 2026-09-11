# OpenShift bundled stack installation with Helm

This procedure installs AgentHub, PostgreSQL/pgvector, Redis and MinIO into one OpenShift namespace.
It is the simplest self-contained demo path, not a production architecture: each dependency has one
replica, internal traffic is plain TCP/HTTP, and backup/restore automation is not included.

## 1. Prerequisites and namespace

On Ubuntu, install `docker` or `podman`, `oc`, Helm 3, `skopeo`, and access to an approved image
registry and an OpenShift storage class. Log in and select a namespace:

```sh
oc login --server='https://api.cluster.example.com:6443' --token='REPLACE'
oc new-project agenthub-demo       # only if it does not already exist and you are authorized
oc project agenthub-demo
```

Do not grant `anyuid`, privileged, or custom SCC access.

## 2. Build and push immutable images

Build the two AgentHub images and the OpenShift-compatible pgvector image. Mirror approved Redis,
MinIO and MinIO Client images into the same registry. The example below shows Docker; Podman accepts
the same build syntax.

```sh
export RELEASE_ID=release-20260803-1
export REGISTRY=registry.example.com/team

docker build --target application --build-arg STATIC_RELEASE_ID="$RELEASE_ID" \
  -t "$REGISTRY/agenthub:$RELEASE_ID" -f deploy/Dockerfile .
docker build --target static-runtime --build-arg STATIC_RELEASE_ID="$RELEASE_ID" \
  -t "$REGISTRY/agenthub-static:$RELEASE_ID" -f deploy/Dockerfile .
docker build -t "$REGISTRY/agenthub-postgresql:$RELEASE_ID" \
  -f deploy/postgres-openshift.Dockerfile .

docker push "$REGISTRY/agenthub:$RELEASE_ID"
docker push "$REGISTRY/agenthub-static:$RELEASE_ID"
docker push "$REGISTRY/agenthub-postgresql:$RELEASE_ID"
```

Mirror organization-approved Redis, MinIO server and `mc` client versions. Resolve every pushed
image to its immutable digest:

```sh
skopeo inspect --format '{{.Digest}}' "docker://$REGISTRY/agenthub:$RELEASE_ID"
skopeo inspect --format '{{.Digest}}' "docker://$REGISTRY/agenthub-static:$RELEASE_ID"
skopeo inspect --format '{{.Digest}}' "docker://$REGISTRY/agenthub-postgresql:$RELEASE_ID"
```

Repeat for Redis, MinIO and `mc`. Do not use `latest` in `stack-values.yaml`.

If the OpenShift build nodes cannot reach upstream registries or the Docker strategy cannot select a
multi-stage target, use the triggerless Binary Build template instead. Base-image parameters may
point at an approved mirror; do not edit the canonical Dockerfiles for one environment:

```sh
oc process -f deploy/openshift/build/template.yaml \
  -p RELEASE_ID="$RELEASE_ID" \
  -p NODE_BASE_IMAGE=registry.example.com/mirror/node@sha256:REPLACE \
  -p PYTHON_BASE_IMAGE=registry.example.com/mirror/python@sha256:REPLACE \
  -p NGINX_BASE_IMAGE=registry.example.com/mirror/nginx-unprivileged@sha256:REPLACE \
  -p PGVECTOR_BASE_IMAGE=registry.example.com/mirror/pgvector@sha256:REPLACE \
  | oc apply -f -
oc start-build agenthub-app --from-dir=. --follow
oc start-build agenthub-static --from-dir=. --follow
oc start-build agenthub-postgresql --from-dir=. --follow
```

Resolve the three resulting ImageStreamTags to digests before populating `stack-values.yaml`.

## 3. Configure credentials and provider endpoints

```sh
cp deploy/helm/agenthub-stack/stack.env.example stack.env
chmod 600 stack.env
vi stack.env
chmod +x deploy/helm/agenthub-stack/scripts/create-stack-secrets.sh
./deploy/helm/agenthub-stack/scripts/create-stack-secrets.sh ./stack.env
```

Set strong, unique PostgreSQL admin/migration/application passwords, a Redis password, separate
MinIO root and AgentHub bucket credentials, Django secret, metrics token and initial console password. The helper creates external Secrets
without storing their values in Helm history. `MODEL_API_KEY` and `EMBEDDING_API_KEY` are the keys
for the OpenAI-compatible LLM and embedding services you supply; they do not need to be Gemini.

The default hostnames assume release name `agenthub-stack`:

- `agenthub-stack-postgresql`
- `agenthub-stack-redis`
- `http://agenthub-stack-minio:9000`

If the release name changes, update all three before creating Secrets/installing.

## 4. Configure non-secret Helm values

```sh
cp deploy/helm/agenthub-stack/values.openshift.example.yaml stack-values.yaml
vi stack-values.yaml
```

Replace all example repositories and all-zero digests. Enter the externally supplied LLM and
embedding host, port, path and model names. Hosts contain no scheme; HTTPS is used for these provider
connections. Embedding dimensions must match the service output and stored vector geometry.

Keep `agenthub.databaseInitialization.mode: jobs`. Its probe image reuses the digest-pinned bundled
PostgreSQL image because that image contains `pg_isready`.

Set the storage class if the namespace has no default. Review the three PVC sizes and all resource
requests/limits against namespace quota and LimitRange. Credentials never belong in this file.

## 5. Build the local chart dependency and preflight

```sh
helm dependency build deploy/helm/agenthub-stack
helm lint deploy/helm/agenthub-stack -f stack-values.yaml --strict
helm template agenthub-stack deploy/helm/agenthub-stack \
  --namespace agenthub-demo -f stack-values.yaml \
  | oc apply --namespace agenthub-demo --dry-run=server -f -
```

The server dry run is mandatory because only the target cluster can evaluate Route support,
restricted SCC mutation, quota, LimitRange, storage classes and admission policy. Fix policy errors
without enabling root, a fixed UID, writable root filesystems, privilege escalation or missing
limits.

## 6. Install

```sh
helm upgrade --install agenthub-stack deploy/helm/agenthub-stack \
  --namespace agenthub-demo \
  -f stack-values.yaml \
  --atomic --wait --wait-for-jobs --timeout 30m
```

PostgreSQL first initialization creates separate admin, migration and runtime roles and enables the
`vector` extension. Helm creates revision-named migration and bootstrap Jobs together with the
StatefulSets. Migration waits for PostgreSQL; bootstrap waits for migrations; application workloads
wait for exact active bootstrap profiles. This preserves `--atomic --wait --wait-for-jobs` without
post-install hook deadlock. The MinIO bucket hook then creates the bucket and attaches a
bucket-scoped policy to the AgentHub S3 identity.

## 7. Verify

```sh
helm status agenthub-stack -n agenthub-demo
oc get pods,statefulsets,deployments,pvc,services,routes -n agenthub-demo
oc rollout status statefulset/agenthub-stack-postgresql -n agenthub-demo
oc rollout status statefulset/agenthub-stack-redis -n agenthub-demo
oc rollout status statefulset/agenthub-stack-minio -n agenthub-demo
helm test agenthub-stack -n agenthub-demo --logs
```

Confirm arbitrary-UID execution and PostgreSQL role/extension state without printing credentials:

```sh
oc exec -n agenthub-demo statefulset/agenthub-stack-postgresql -- id
oc exec -n agenthub-demo statefulset/agenthub-stack-postgresql -- \
  sh -c 'test "$(id -u)" -ne 0 && psql -U "$POSTGRES_USER" -d "$AGENTHUB_DATABASE" -Atc \
  "select extname from pg_extension where extname='\''vector'\''"'
```

Open the AgentHub Route at `/console/`. For a fresh database, the login is the platform actor defined
by the AgentHub chart (default `platform-admin`) and the `BOOTSTRAP_ADMIN_PASSWORD` from `stack.env`.
After successful first login, remove the one-time bootstrap Secret:

```sh
oc delete secret agenthub-bootstrap-credentials -n agenthub-demo
```

## 8. Upgrade, rollback and data lifecycle

Before any upgrade, take and test application-consistent backups of PostgreSQL and MinIO and confirm
Redis persistence expectations. Use new immutable digests and rerun lint/server dry-run/install.
PostgreSQL major, Redis format and MinIO compatibility upgrades require their vendor-specific
procedures; a Helm rollback cannot reverse Django migrations or stored data formats.

The PostgreSQL init script runs only when its PVC is empty. Updating the Secret does **not** rotate
roles in an existing database. Rotate existing PostgreSQL roles with an approved, audited database
procedure first, then update Secrets and restart affected workloads. Secret changes alone also do
not force a Kubernetes rollout; explicitly restart the relevant StatefulSet/Deployments after a
reviewed Redis, MinIO or provider-key rotation.

```sh
helm history agenthub-stack -n agenthub-demo
helm rollback agenthub-stack PREVIOUS_REVISION -n agenthub-demo --wait --timeout 30m
helm uninstall agenthub-stack -n agenthub-demo
```

Uninstall removes workloads and Services, while each StatefulSet's explicit retention policy keeps
its PVC; externally created Secrets are also retained. Inspect them explicitly. PVC, Secret, database and bucket deletion
is a separate destructive operation and is not part of this guide.

## Production boundary

For production, use `deploy/helm/agenthub` with platform-managed, highly available, TLS-protected
PostgreSQL/pgvector, Redis and object storage; define backups, restore tests, monitoring, alerting,
capacity plans and documented recovery objectives. Do not promote this bundled topology by merely
increasing replica counts.
