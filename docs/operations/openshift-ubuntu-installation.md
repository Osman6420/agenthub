# AgentHub OpenShift installation from Ubuntu

> The preferred packaged path is the [Helm installation guide](openshift-helm-installation.md).
> This document remains the lower-level `oc process`/OpenShift Template alternative and the detailed
> source for image, provider, network and operational constraints.

This guide installs AgentHub and, optionally, the standalone external-consumer showcase from an
Ubuntu terminal using `oc`. It is designed for OpenShift's default restricted SCC: workloads do not
request root, a fixed UID, privilege escalation, Linux capabilities or Kubernetes API credentials.
Every container and Job declares CPU, memory and ephemeral-storage requests and limits.

The installer creates namespace-scoped application resources only. It does **not** install or reset
PostgreSQL, Redis, S3-compatible storage, cluster ingress, registry credentials, trust bundles,
operators or SCCs. Those remain platform-owned prerequisites.

> No live target-cluster admission has been performed from this repository workstation. Run the
> server-side dry run and the verification section against the exact target cluster before the
> presentation or production approval.

## 1. Deployment topology

The install path creates these roles from one immutable application image:

- `agenthub-web`: two ASGI replicas, public only through the TLS Route;
- `agenthub-worker-runtime`: asynchronous workflow/agent execution;
- `agenthub-worker-ingestion`: document parsing, embedding and index builds;
- `agenthub-worker-eval`: evaluation jobs;
- `agenthub-beat`: one scheduler replica with a writable bounded `/tmp` schedule;
- one release-specific migration Job and bootstrap Job;
- `agenthub-static`: two non-root Nginx replicas built from the same release;
- optionally, `agenthub-external-demo`: a separate narrow reverse proxy with server-side consumer
  tokens and its own TLS Route.

PostgreSQL/pgvector, Redis and object storage are external managed services. Model and embedding
requests use separately supplied OpenAI-compatible HTTPS endpoints.

## 2. Prerequisites

On Ubuntu:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl grep coreutils openssl python3 skopeo
oc version --client
oc login https://api.<cluster>:6443
oc whoami
```

Use the organization's approved Docker or Podman installation for image builds; the examples below
use `docker`.

The logged-in identity needs namespace-scoped permission to create/update Secrets, ConfigMaps,
ServiceAccounts, Jobs, Deployments, Services, Routes and NetworkPolicies; patch Deployments;
recreate release Jobs; and delete the one-time bootstrap Secret. It does not need
`cluster-admin`, SCC mutation or permission to use `anyuid`/`privileged`.

Required services:

1. PostgreSQL 16 with the `vector` extension and two credentials:
   - migration URL: reviewed schema-owner/migrator;
   - runtime URL: non-owner, non-superuser, `NOBYPASSRLS` application role with the repository's
     exact grant matrix. Follow [Phase 2 application-role rollout](phase-2-app-role-rollout.md) and
     [RLS readiness](phase-2-rls-readiness.md).
2. Redis reachable by every application role; TLS (`rediss://`) is preferred outside a trusted
   service mesh.
3. S3-compatible object storage, a pre-created bucket and least-privilege access/secret keys.
4. An image registry reachable by OpenShift nodes.
5. Approved DNS, TLS trust and egress for PostgreSQL, Redis, object storage, the model endpoint, the
   embedding endpoint and—when installing the showcase—`tr.wikipedia.org:443`.

If the registry is private, attach an approved image-pull Secret to the installer-created service
accounts before rollout or configure the namespace's standard pull credential. Never place registry
credentials in the templates.

## 3. Build and push immutable images

Use one release identifier for the application and static images. It must be a lowercase DNS label
of at most 40 characters because it is also used in Job names and the static URL.

```sh
export RELEASE_ID=release-2026-08-03
export REGISTRY=registry.example.com/team

docker build \
  --target application \
  --build-arg STATIC_RELEASE_ID="$RELEASE_ID" \
  -t "$REGISTRY/agenthub:$RELEASE_ID" \
  -f deploy/Dockerfile .

docker build \
  --target static-runtime \
  --build-arg STATIC_RELEASE_ID="$RELEASE_ID" \
  -t "$REGISTRY/agenthub-static:$RELEASE_ID" \
  -f deploy/Dockerfile .

docker build \
  -t "$REGISTRY/agenthub-external-demo:$RELEASE_ID" \
  -f deploy/external-demo.Dockerfile .

docker push "$REGISTRY/agenthub:$RELEASE_ID"
docker push "$REGISTRY/agenthub-static:$RELEASE_ID"
docker push "$REGISTRY/agenthub-external-demo:$RELEASE_ID"
```

Resolve the registry digests and use `repository@sha256:...`, never a mutable tag. With `skopeo`:

```sh
skopeo inspect "docker://$REGISTRY/agenthub:$RELEASE_ID" | grep '"Digest"'
skopeo inspect "docker://$REGISTRY/agenthub-static:$RELEASE_ID" | grep '"Digest"'
skopeo inspect "docker://$REGISTRY/agenthub-external-demo:$RELEASE_ID" | grep '"Digest"'
```

The production settings compare the application image's embedded release id with
`AGENTHUB_STATIC_RELEASE_ID`. A mismatch fails closed. Promote and roll back the application digest,
static digest and release id together.

## 4. Configure non-Gemini model and embedding providers

AgentHub does not require Gemini. The installer registers two immutable, provider-neutral
`openai_compatible` profiles:

- chat: `POST https://<MODEL_HOST>:<MODEL_PORT><MODEL_PATH>`;
- embedding: `POST https://<EMBEDDING_HOST>:<EMBEDDING_PORT><EMBEDDING_PATH>`.

The chat endpoint must accept an OpenAI-compatible chat-completions request and return
`choices[0].message.content`. The embedding endpoint must accept `{"model": ..., "input": [...]}`
and return one `data[].embedding` vector per input. Authentication is
`Authorization: Bearer <API key>`.

Supply host, path, model name and API key separately. Do not put a scheme in `*_HOST`, do not put a
query string in `*_PATH`, and do not put an endpoint or key in scenario artifacts. The API keys are
stored only as OpenShift Secret keys:

- `MODEL_SECRET_PRIMARY` for profile reference `secret:primary`;
- `EMBEDDING_SECRET_PRIMARY` for profile reference `secret:primary`.

Set `EMBEDDING_INDEX_TYPE=vector` for up to 2,000 stored dimensions or `halfvec` for up to 4,000.
`EMBEDDING_DIMENSIONS` must match the governed stored geometry. An explicit `halfvec(4000)` profile
may apply the bounded provider-response behavior documented in
[ADR-0017](../adr/0017-bounded-halfvec-response-truncation.md); every other geometry
requires exact provider output length. A different dimension, index type or model requires a new
profile revision and a staged reindex; never edit an existing profile in place.

The current shared SSRF-safe transport accepts valid HTTPS destinations that resolve to public
unicast addresses. If the target model gateway resolves to RFC1918, loopback, link-local or another
private address, calls fail closed. Supporting a private corporate model gateway requires a reviewed
private-egress policy/code path; do not bypass destination validation or disable TLS verification.
For an internal CA, add the approved CA through the platform/image trust process rather than using
an insecure TLS flag.

## 5. Prepare the protected installer configuration

Copy the example outside Git tracking and restrict its permissions:

```sh
cp deploy/openshift/install/openshift.env.example deploy/openshift/install/openshift.env
chmod 600 deploy/openshift/install/openshift.env
```

Edit every `REPLACE` value. Generate independent secrets:

```sh
openssl rand -base64 48  # DJANGO_SECRET_KEY
openssl rand -base64 32  # METRICS_BEARER_TOKEN
openssl rand -base64 24  # BOOTSTRAP_ADMIN_PASSWORD
```

The config file is trusted POSIX shell syntax. Single-quote values that contain `$`, whitespace,
`#`, backticks or other shell-significant characters—for example
`MODEL_API_KEY='literal$value'`. Do not source a configuration received from an untrusted party.

Important fields:

| Variable | Meaning |
| --- | --- |
| `APPLICATION_IMAGE`, `STATIC_IMAGE`, `DEMO_IMAGE` | Registry references pinned by SHA-256 digest |
| `DATABASE_URL` | Restricted runtime application role |
| `MIGRATION_DATABASE_URL` | Separate reviewed migration/schema-owner role |
| `MODEL_HOST/PATH/NAME/API_KEY` | Chat-completions endpoint configuration |
| `EMBEDDING_HOST/PATH/NAME/API_KEY/DIMENSIONS/INDEX_TYPE` | Embedding endpoint and governed vector geometry |
| `PLATFORM_ACTOR` | Initial recovery superuser created only if absent |
| `INSTALL_EXTERNAL_DEMO` | `true` to seed and expose the external showcase |

The installer never enables shell tracing. It places secret values in a mode-`0600` temporary
directory, creates OpenShift Secrets from protected env files, and removes the local directory on
exit. The one-time bootstrap password Secret is deleted after the bootstrap Job. Existing recovery
accounts are not silently password-rotated on a rerun.

`PLATFORM_ACTOR` is an exceptional recovery superuser used to bootstrap immutable platform
profiles. After installation, create and assign a non-superuser Global Administrator for daily
operations according to the responsibility model; do not use the recovery identity as the routine
shared administrator.

Do not commit `openshift.env`. It is ignored by the repository, but filesystem and shell-history
controls remain the operator's responsibility.

## 6. Preflight render and server-side admission

The installer itself performs fail-closed value and permission checks. Before the first deployment,
render the templates with non-secret placeholder values and use the target cluster's server-side
dry run. The simplest full check is to use a dedicated disposable namespace and a configuration
whose Secret values are test-only, then inspect without exposing the generated YAML:

```sh
oc auth can-i create deployments.apps -n agenthub-demo
oc auth can-i create jobs.batch -n agenthub-demo
oc auth can-i create routes.route.openshift.io -n agenthub-demo
oc auth can-i create networkpolicies.networking.k8s.io -n agenthub-demo

oc process -n agenthub-demo \
  -f deploy/openshift/install/agenthub-template.yaml \
  -p APPLICATION_IMAGE='<application@sha256:digest>' \
  -p STATIC_IMAGE='<static@sha256:digest>' \
  -p RELEASE_ID='release-2026-08-03' \
  -p ROUTE_HOST='agenthub-demo.apps.cluster.example.com' \
  -p NAMESPACE='agenthub-demo' \
  -p OBJECT_STORE_ENDPOINT='https://s3.example.com' \
  -p OBJECT_STORE_BUCKET='agenthub-demo' \
  -p OBJECT_STORE_REGION='us-east-1' \
  | oc apply -n agenthub-demo --dry-run=server -f -
```

Do not use `--validate=false` to conceal an admission error. Fix quota, image, SCC or schema
problems explicitly.

## 7. Install

Run from the repository root on Ubuntu:

```sh
chmod +x deploy/openshift/install/install.sh
./deploy/openshift/install/install.sh deploy/openshift/install/openshift.env
```

Normal behavior is idempotent at the release level:

1. validate inputs, image digests, `oc` login and namespace permissions;
2. create/update namespace Secrets and ConfigMaps;
3. run and wait for the release-specific migration Job;
4. create the recovery actor if absent and register profile revision 1 if absent;
5. delete the one-time bootstrap password Secret;
6. deploy static, web, runtime, ingestion, evaluation and beat roles;
7. restart the deployments so rotated Secret values are loaded, then wait for every rollout and the
   HTTPS readiness endpoint;
8. optionally seed Wikipedia with the configured generic embedding/model profiles, create the
   server-side demo credential Secret and deploy the external-demo Route.

The script prints the console and optional demo URLs plus the non-secret username. It does not print
the generated password, consumer tokens or provider keys. Retrieve only the demo password when it is
needed, without printing the consumer-token portion of the credential document:

```sh
oc get secret agenthub-external-demo-credentials -n "$NAMESPACE" \
  -o 'jsonpath={.data.credentials\.json}' \
  | base64 -d \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["operator"]["password"])'
```

The demo server reads the full credential document from its Secret, but tokens are never sent to the
browser.

The release-scoped migration and bootstrap Jobs are recreated on an installer rerun. Django
migrations are idempotent, and recreating the bootstrap Job lets a newly selected immutable profile
revision be registered. Registered profiles are platform catalog entries. A normal tenant still
needs an explicit embedding-profile grant and must pin the desired model/embedding profile in its
governed artifacts. The optional external-demo seeder creates only the grant required by its own
isolated organization.

## 8. Restricted SCC and quota verification

No manifest sets `runAsUser`; restricted SCC assigns a namespace-range UID. Verify the admitted
pods instead of assuming the source YAML was preserved:

```sh
oc get pods -n "$NAMESPACE" -o wide
oc get pod -n "$NAMESPACE" -l app.kubernetes.io/name=agenthub-web \
  -o jsonpath='{range .items[*]}{.metadata.name}{" uid="}{.spec.securityContext.runAsUser}{" scc="}{.metadata.annotations.openshift\.io/scc}{"\n"}{end}'

oc get pods -n "$NAMESPACE" -o jsonpath='{range .items[*].spec.containers[*]}{.name}{" requests="}{.resources.requests}{" limits="}{.resources.limits}{"\n"}{end}'

oc exec -n "$NAMESPACE" deployment/agenthub-web -- id
oc exec -n "$NAMESPACE" deployment/agenthub-web -- sh -c 'test "$(id -u)" -ne 0 && test ! -w /app && test -w /tmp'
```

Expected properties:

- UID is non-zero and may differ between namespaces;
- SCC is the cluster's restricted/restricted-v2 equivalent, never `anyuid` or `privileged`;
- every container has CPU, memory and ephemeral-storage requests and limits;
- `/app` and the root filesystem are read-only while bounded `/tmp` is writable;
- `allowPrivilegeEscalation=false`, all capabilities are dropped and seccomp is RuntimeDefault;
- `automountServiceAccountToken=false` for every workload.

Do not solve admission failures by granting `anyuid`, running root, removing limits, making the root
filesystem writable or weakening the SCC.

## 9. Functional verification

```sh
oc get routes -n "$NAMESPACE"
curl --fail --show-error "https://$ROUTE_HOST/v1/health/live"
curl --fail --show-error "https://$ROUTE_HOST/v1/health/ready"

oc get jobs -n "$NAMESPACE"
oc logs -n "$NAMESPACE" "job/agenthub-migrate-$RELEASE_ID" --tail=100
oc logs -n "$NAMESPACE" "job/agenthub-bootstrap-$RELEASE_ID" --tail=100

oc get deploy -n "$NAMESPACE"
oc exec -n "$NAMESPACE" deployment/agenthub-worker-ingestion -- \
  python manage.py check_ingestion_preflight --require-worker
```

For the showcase:

```sh
curl --fail --show-error "https://$DEMO_ROUTE_HOST/healthz"
curl --fail --show-error "https://$DEMO_ROUTE_HOST/demo-config"
```

The `/demo-config` response must contain consumer names/scenarios but no token, bearer credential,
operator password or API key. In the browser, run all four scenarios and the expected 403 isolation
test.

To verify provider configuration without leaking keys:

```sh
oc exec -n "$NAMESPACE" deployment/agenthub-web -- python manage.py shell -c \
  'from apps.orchestration.models import ModelProfile; print(list(ModelProfile.objects.values_list("logical_id", "revision", "host", "model", "status")))'

oc exec -n "$NAMESPACE" deployment/agenthub-web -- python manage.py shell -c \
  'from apps.ingestion.models import EmbeddingProfile; print(list(EmbeddingProfile.objects.values_list("logical_id", "revision", "host", "model", "dimensions", "status")))'
```

These queries intentionally omit `secret_ref` and never resolve or print API keys.

## 10. Network policy and egress

The generic installer applies default-deny **ingress** to pods labeled as part of AgentHub (not to
unrelated workloads that may share the namespace) and explicit Route/demo-to-web ingress.
It does not guess egress CIDRs because Kubernetes NetworkPolicy cannot safely express arbitrary DNS
provider names and cluster environments differ in CNI, proxy, service mesh and managed-service
topology.

Before production approval, the platform team must add reviewed egress controls for:

- OpenShift DNS;
- PostgreSQL and Redis;
- object storage;
- model and embedding HTTPS destinations;
- approved ingestion sources, including Wikipedia only when the showcase is enabled;
- optional OTLP/LDAP endpoints if those features are enabled.

The repository's [default-deny draft](../../deploy/openshift/network-policies.yaml) demonstrates the
deny-first shape but must not be applied alone: it intentionally blocks all environment-specific
dependencies until matching egress policies exist. Never use a permanent `0.0.0.0/0` egress rule as
the production solution.

## 11. Upgrade and rollback

For an upgrade:

1. build all images from one reviewed commit and a new `RELEASE_ID`;
2. resolve new immutable digests;
3. back up PostgreSQL/object data and review migrations;
4. increment profile revisions only when endpoint/model/dimension settings change;
5. update the protected env file and rerun the installer;
6. retain prior image digests/static image for the rollback window.

Rollback reapplies the previous application/static digests and their matching release id. Do not
automatically reverse migrations. If a forward migration is not backward-compatible, stop and use
its reviewed database rollback/restore procedure.

## 12. Troubleshooting

Admission or quota failure:

```sh
oc get events -n "$NAMESPACE" --sort-by=.lastTimestamp | tail -n 50
oc describe pod -n "$NAMESPACE" <pod>
oc describe resourcequota -n "$NAMESPACE"
oc describe limitrange -n "$NAMESPACE"
```

Migration/bootstrap failure:

```sh
oc logs -n "$NAMESPACE" "job/agenthub-migrate-$RELEASE_ID" --all-containers --tail=200
oc logs -n "$NAMESPACE" "job/agenthub-bootstrap-$RELEASE_ID" --all-containers --tail=200
```

The normal success/failure path removes `agenthub-bootstrap-credentials`. If the operator interrupted
the process while the bootstrap Job was running, inspect the Job first, then remove that one-time
Secret explicitly:

```sh
oc delete secret agenthub-bootstrap-credentials -n "$NAMESPACE" --ignore-not-found
```

Runtime failure:

```sh
oc logs -n "$NAMESPACE" deployment/agenthub-web --tail=200
oc logs -n "$NAMESPACE" deployment/agenthub-worker-runtime --tail=200
oc logs -n "$NAMESPACE" deployment/agenthub-worker-ingestion --tail=200
```

Common fail-closed causes:

- `AGENTHUB_IMAGE_RELEASE_ID` does not match the configured static release;
- target image is not accessible by digest;
- runtime database role owns tables, is superuser/`BYPASSRLS`, or lacks the exact grants;
- provider hostname resolves to a private/non-approved address;
- API path is not OpenAI-compatible;
- embedding dimension differs from the profile;
- custom CA is absent from the image/platform trust store;
- egress policy, proxy or service mesh blocks the destination;
- object bucket/permissions are missing.

## 13. Uninstall boundary

There is deliberately no automatic uninstall/reset command. Removing a namespace, database, bucket,
Secret or PVC is destructive and requires explicit owner approval plus backup/retention review.

To remove only the stateless showcase after the presentation:

```sh
oc delete -n "$NAMESPACE" \
  route/agenthub-external-demo service/agenthub-external-demo \
  deployment/agenthub-external-demo serviceaccount/agenthub-external-demo \
  networkpolicy/agenthub-external-demo-ingress networkpolicy/agenthub-demo-to-web
oc delete -n "$NAMESPACE" secret/agenthub-external-demo-credentials
```

This does not delete the `external-demo` database rows. Database data removal is a separate,
explicitly destructive operation and is not part of the installation guide.
