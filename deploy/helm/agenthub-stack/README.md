# AgentHub bundled OpenShift stack

This umbrella chart installs AgentHub, PostgreSQL with pgvector, Redis and MinIO in the same
namespace. It is intended for demonstrations and controlled non-production environments. The
dependencies are single replica, use unencrypted namespace-internal connections and do not include
backup automation; use the `agenthub` chart with approved managed services for production.

The chart creates no SCC, cluster role or plaintext Secret. Workloads accept OpenShift-assigned
arbitrary UIDs, drop all capabilities, use `RuntimeDefault` seccomp and read-only root filesystems,
and define CPU, memory and ephemeral-storage requests and limits. PostgreSQL, Redis and MinIO have
one retained PVC each and no Route.

Use the complete Ubuntu/OpenShift procedure in
[`docs/operations/openshift-bundled-stack-helm.md`](../../../docs/operations/openshift-bundled-stack-helm.md).

Quick command sequence after building and pushing digest-pinned images:

```sh
cp deploy/helm/agenthub-stack/stack.env.example stack.env
chmod 600 stack.env
vi stack.env
./deploy/helm/agenthub-stack/scripts/create-stack-secrets.sh ./stack.env

cp deploy/helm/agenthub-stack/values.openshift.example.yaml stack-values.yaml
vi stack-values.yaml
helm dependency build deploy/helm/agenthub-stack
helm lint deploy/helm/agenthub-stack -f stack-values.yaml --strict
helm template agenthub-stack deploy/helm/agenthub-stack \
  -n agenthub-demo -f stack-values.yaml | oc apply -n agenthub-demo --dry-run=server -f -
helm upgrade --install agenthub-stack deploy/helm/agenthub-stack \
  -n agenthub-demo -f stack-values.yaml --atomic --wait --wait-for-jobs --timeout 30m
```

Keep the release name `agenthub-stack` unless the service hostnames in `stack.env` and the MinIO
endpoint in values are changed to match the resulting release-scoped names.

The bundled values select `databaseInitialization.mode: jobs`. Migration and bootstrap are normal,
Helm-managed Jobs named for the release revision, so PostgreSQL can be created by the same release
without a `post-install`/`--wait` cycle. Do not change this stack to post-install hooks or remove
`--wait-for-jobs`.
