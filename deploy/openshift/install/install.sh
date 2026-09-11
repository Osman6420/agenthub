#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
TMP_DIR=""

info() {
    printf '%s\n' "[agenthub] $*"
}

die() {
    printf '%s\n' "[agenthub] ERROR: $*" >&2
    exit 1
}

cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT HUP INT TERM

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_var() {
    eval "value=\${$1-}"
    [ -n "$value" ] || die "required variable is empty: $1"
    case "$value" in
        *'
'*) die "$1 must not contain a newline" ;;
    esac
}

validate_digest_image() {
    printf '%s' "$2" | grep -Eq '@sha256:[0-9a-fA-F]{64}$' || \
        die "$1 must be an immutable image reference ending in @sha256:<64 hex>"
}

validate_dns_name() {
    printf '%s' "$2" | grep -Eq '^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?(\.[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?)*$' || \
        die "$1 must be a lowercase DNS name without a scheme or path"
}

validate_namespace() {
    printf '%s' "$1" | grep -Eq '^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$' || \
        die "NAMESPACE must be one lowercase DNS label of at most 63 characters"
}

validate_path() {
    case "$2" in
        /*) ;;
        *) die "$1 must start with /" ;;
    esac
    case "$2" in
        *'?'*|*'#'*) die "$1 must not contain query or fragment data" ;;
    esac
}

validate_integer() {
    printf '%s' "$2" | grep -Eq '^[1-9][0-9]*$' || die "$1 must be a positive integer"
}

validate_slug() {
    printf '%s' "$2" | grep -Eq '^[a-z0-9][a-z0-9._-]{0,126}[a-z0-9]$|^[a-z0-9]$' || \
        die "$1 must contain only lowercase letters, digits, dot, underscore or hyphen"
}

write_env_value() {
    printf '%s=%s\n' "$2" "$3" >> "$1"
}

apply_secret_file() {
    secret_name=$1
    env_file=$2
    oc create secret generic "$secret_name" \
        --namespace "$NAMESPACE" \
        --from-env-file="$env_file" \
        --dry-run=client -o yaml | oc apply --namespace "$NAMESPACE" -f - >/dev/null
}

wait_job() {
    job_name=$1
    timeout=$2
    if ! oc wait --namespace "$NAMESPACE" --for=condition=complete "job/$job_name" \
        --timeout="$timeout"; then
        oc logs --namespace "$NAMESPACE" "job/$job_name" --all-containers=true --tail=200 || true
        die "job failed or timed out: $job_name"
    fi
}

if [ "$#" -gt 1 ]; then
    die "usage: $0 [trusted-config-file]"
fi
if [ "$#" -eq 1 ]; then
    [ -r "$1" ] || die "config file is not readable: $1"
    # The operator-owned file is shell syntax so values with URL punctuation remain intact.
    # shellcheck disable=SC1090
    . "$1"
fi

require_command oc
require_command curl
require_command grep
require_command mktemp
require_command base64

for name in \
    NAMESPACE RELEASE_ID APPLICATION_IMAGE STATIC_IMAGE ROUTE_HOST \
    DATABASE_URL MIGRATION_DATABASE_URL REDIS_URL OBJECT_STORE_ENDPOINT OBJECT_STORE_BUCKET OBJECT_STORE_REGION \
    AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY DJANGO_SECRET_KEY METRICS_BEARER_TOKEN \
    BOOTSTRAP_ADMIN_PASSWORD PLATFORM_ACTOR MODEL_API_KEY MODEL_LOGICAL_ID MODEL_REVISION \
    MODEL_HOST MODEL_PORT MODEL_PATH MODEL_NAME EMBEDDING_API_KEY EMBEDDING_LOGICAL_ID \
    EMBEDDING_REVISION EMBEDDING_HOST EMBEDDING_PORT EMBEDDING_PATH EMBEDDING_NAME \
    EMBEDDING_DIMENSIONS EMBEDDING_INDEX_TYPE
do
    require_var "$name"
done

CREATE_NAMESPACE=${CREATE_NAMESPACE:-false}
INSTALL_EXTERNAL_DEMO=${INSTALL_EXTERNAL_DEMO:-false}

validate_digest_image APPLICATION_IMAGE "$APPLICATION_IMAGE"
validate_digest_image STATIC_IMAGE "$STATIC_IMAGE"
validate_namespace "$NAMESPACE"
validate_dns_name ROUTE_HOST "$ROUTE_HOST"
validate_dns_name MODEL_HOST "$MODEL_HOST"
validate_dns_name EMBEDDING_HOST "$EMBEDDING_HOST"
validate_path MODEL_PATH "$MODEL_PATH"
validate_path EMBEDDING_PATH "$EMBEDDING_PATH"
validate_integer MODEL_PORT "$MODEL_PORT"
validate_integer EMBEDDING_PORT "$EMBEDDING_PORT"
validate_integer MODEL_REVISION "$MODEL_REVISION"
validate_integer EMBEDDING_REVISION "$EMBEDDING_REVISION"
validate_integer EMBEDDING_DIMENSIONS "$EMBEDDING_DIMENSIONS"
validate_slug MODEL_LOGICAL_ID "$MODEL_LOGICAL_ID"
validate_slug EMBEDDING_LOGICAL_ID "$EMBEDDING_LOGICAL_ID"
[ "$MODEL_PORT" -le 65535 ] || die "MODEL_PORT must be at most 65535"
[ "$EMBEDDING_PORT" -le 65535 ] || die "EMBEDDING_PORT must be at most 65535"
case "$EMBEDDING_INDEX_TYPE" in
    vector)
        [ "$EMBEDDING_DIMENSIONS" -le 2000 ] || \
            die "vector profiles support at most 2000 dimensions"
        ;;
    halfvec)
        [ "$EMBEDDING_DIMENSIONS" -le 4000 ] || \
            die "halfvec profiles support at most 4000 dimensions"
        ;;
    *) die "EMBEDDING_INDEX_TYPE must be vector or halfvec" ;;
esac
printf '%s' "$RELEASE_ID" | grep -Eq '^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$' || \
    die "RELEASE_ID must be a lowercase DNS label of at most 40 characters"

printf '%s' "$OBJECT_STORE_ENDPOINT" | \
    grep -Eq '^https?://[A-Za-z0-9]([-A-Za-z0-9.]*[A-Za-z0-9])?([:][1-9][0-9]{0,4})?(/[^?#]*)?$' || \
    die "OBJECT_STORE_ENDPOINT must be an HTTP(S) origin/path without credentials, query or fragment"
case "$CREATE_NAMESPACE" in true|false) ;; *) die "CREATE_NAMESPACE must be true or false" ;; esac
case "$INSTALL_EXTERNAL_DEMO" in true|false) ;; *) die "INSTALL_EXTERNAL_DEMO must be true or false" ;; esac

if [ "$INSTALL_EXTERNAL_DEMO" = true ]; then
    require_command python3
    require_var DEMO_IMAGE
    require_var DEMO_ROUTE_HOST
    validate_digest_image DEMO_IMAGE "$DEMO_IMAGE"
    validate_dns_name DEMO_ROUTE_HOST "$DEMO_ROUTE_HOST"
fi

oc whoami >/dev/null 2>&1 || die "oc is not logged in"
if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
    [ "$CREATE_NAMESPACE" = true ] || \
        die "namespace does not exist; create it first or set CREATE_NAMESPACE=true"
    info "creating namespace $NAMESPACE"
    oc new-project "$NAMESPACE" >/dev/null
fi
for resource in secrets configmaps serviceaccounts jobs.batch deployments.apps services routes.route.openshift.io networkpolicies.networking.k8s.io
do
    oc auth can-i create "$resource" --namespace "$NAMESPACE" | grep -qx yes || \
        die "current oc identity cannot create $resource in $NAMESPACE"
done
oc auth can-i patch deployments.apps --namespace "$NAMESPACE" | grep -qx yes || \
    die "current oc identity cannot restart deployments in $NAMESPACE"
oc auth can-i delete jobs.batch --namespace "$NAMESPACE" | grep -qx yes || \
    die "current oc identity cannot recreate release jobs in $NAMESPACE"
oc auth can-i delete secrets --namespace "$NAMESPACE" | grep -qx yes || \
    die "current oc identity cannot remove the one-time bootstrap secret in $NAMESPACE"

TMP_DIR=$(mktemp -d)
chmod 700 "$TMP_DIR"

web_env="$TMP_DIR/web.env"
runtime_env="$TMP_DIR/runtime.env"
ingestion_env="$TMP_DIR/ingestion.env"
beat_env="$TMP_DIR/beat.env"
migration_env="$TMP_DIR/migration.env"
bootstrap_env="$TMP_DIR/bootstrap.env"
provider_env="$TMP_DIR/provider.env"

write_env_value "$web_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$web_env" DATABASE_URL "$DATABASE_URL"
write_env_value "$web_env" REDIS_URL "$REDIS_URL"
write_env_value "$web_env" METRICS_BEARER_TOKEN "$METRICS_BEARER_TOKEN"
write_env_value "$web_env" MODEL_SECRET_PRIMARY "$MODEL_API_KEY"
write_env_value "$web_env" AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"
write_env_value "$web_env" AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"

write_env_value "$runtime_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$runtime_env" DATABASE_URL "$DATABASE_URL"
write_env_value "$runtime_env" REDIS_URL "$REDIS_URL"
write_env_value "$runtime_env" MODEL_SECRET_PRIMARY "$MODEL_API_KEY"

write_env_value "$ingestion_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$ingestion_env" DATABASE_URL "$DATABASE_URL"
write_env_value "$ingestion_env" REDIS_URL "$REDIS_URL"
write_env_value "$ingestion_env" AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"
write_env_value "$ingestion_env" AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"
write_env_value "$ingestion_env" EMBEDDING_SECRET_PRIMARY "$EMBEDDING_API_KEY"

write_env_value "$beat_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$beat_env" DATABASE_URL "$DATABASE_URL"
write_env_value "$beat_env" REDIS_URL "$REDIS_URL"
write_env_value "$migration_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$migration_env" DATABASE_URL "$MIGRATION_DATABASE_URL"
write_env_value "$migration_env" REDIS_URL "$REDIS_URL"
write_env_value "$bootstrap_env" BOOTSTRAP_ADMIN_PASSWORD "$BOOTSTRAP_ADMIN_PASSWORD"

for pair in \
    "PLATFORM_ACTOR=$PLATFORM_ACTOR" \
    "MODEL_LOGICAL_ID=$MODEL_LOGICAL_ID" "MODEL_REVISION=$MODEL_REVISION" \
    "MODEL_HOST=$MODEL_HOST" "MODEL_PORT=$MODEL_PORT" "MODEL_PATH=$MODEL_PATH" \
    "MODEL_NAME=$MODEL_NAME" "EMBEDDING_LOGICAL_ID=$EMBEDDING_LOGICAL_ID" \
    "EMBEDDING_REVISION=$EMBEDDING_REVISION" "EMBEDDING_HOST=$EMBEDDING_HOST" \
    "EMBEDDING_PORT=$EMBEDDING_PORT" "EMBEDDING_PATH=$EMBEDDING_PATH" \
    "EMBEDDING_NAME=$EMBEDDING_NAME" "EMBEDDING_DIMENSIONS=$EMBEDDING_DIMENSIONS" \
    "EMBEDDING_INDEX_TYPE=$EMBEDDING_INDEX_TYPE"
do
    printf '%s\n' "$pair" >> "$provider_env"
done

info "applying namespace-scoped secrets"
apply_secret_file agenthub-web-secrets "$web_env"
apply_secret_file agenthub-runtime-secrets "$runtime_env"
apply_secret_file agenthub-ingestion-secrets "$ingestion_env"
apply_secret_file agenthub-beat-secrets "$beat_env"
apply_secret_file agenthub-migration-secrets "$migration_env"
apply_secret_file agenthub-bootstrap-credentials "$bootstrap_env"

oc create configmap agenthub-provider-config --namespace "$NAMESPACE" \
    --from-env-file="$provider_env" --dry-run=client -o yaml | \
    oc apply --namespace "$NAMESPACE" -f - >/dev/null

oc create configmap agenthub-config --namespace "$NAMESPACE" \
    --from-literal=DJANGO_SETTINGS_MODULE=config.settings.production \
    --from-literal=DJANGO_ALLOWED_HOSTS="$ROUTE_HOST,agenthub-web,agenthub-web.$NAMESPACE.svc" \
    --from-literal=AGENTHUB_STATIC_RELEASE_ID="$RELEASE_ID" \
    --from-literal=DJANGO_STATIC_URL="/static/$RELEASE_ID/" \
    --from-literal=DJANGO_SECURE_SSL_REDIRECT=true \
    --from-literal=RUNTIME_MODEL_PROVIDER=apps.orchestration.providers.OpenAICompatibleModelProvider \
    --from-literal=RUNTIME_EMBEDDING_PROVIDER=apps.ingestion.embedding.OpenAICompatibleEmbeddingClient \
    --from-literal=RUNTIME_RETRIEVAL_PROVIDER=apps.retrieval.providers.PgvectorRetrievalProvider \
    --from-literal=OBJECT_STORE_ENDPOINT="$OBJECT_STORE_ENDPOINT" \
    --from-literal=OBJECT_STORE_BUCKET="$OBJECT_STORE_BUCKET" \
    --from-literal=OBJECT_STORE_REGION="$OBJECT_STORE_REGION" \
    --from-literal=DOCUMENTS_OBJECT_STORE_BACKEND=s3 \
    --from-literal=MCP_ENABLED=false \
    --from-literal=METRICS_ENABLED=true \
    --from-literal=OTEL_SERVICE_NAME=agenthub \
    --from-literal=OTEL_EXPORTER_OTLP_ENDPOINT= \
    --from-literal=OTEL_EXPORTER_OTLP_ALLOWED_HOSTS= \
    --from-literal=PYTHON_NODE_RUNTIME_ENABLED=false \
    --from-literal=TOOL_ADAPTER=deterministic \
    --dry-run=client -o yaml | oc apply --namespace "$NAMESPACE" -f - >/dev/null

migration_job="agenthub-migrate-$RELEASE_ID"
info "running migration job $migration_job"
oc delete job "$migration_job" --namespace "$NAMESPACE" --ignore-not-found --wait=true >/dev/null
oc process --namespace "$NAMESPACE" -f "$SCRIPT_DIR/migration-template.yaml" \
    -p "APPLICATION_IMAGE=$APPLICATION_IMAGE" -p "RELEASE_ID=$RELEASE_ID" | \
    oc apply --namespace "$NAMESPACE" -f - >/dev/null
wait_job "$migration_job" 15m

bootstrap_job="agenthub-bootstrap-$RELEASE_ID"
info "creating recovery actor and immutable provider profiles"
oc delete job "$bootstrap_job" --namespace "$NAMESPACE" --ignore-not-found --wait=true >/dev/null
oc process --namespace "$NAMESPACE" -f "$SCRIPT_DIR/bootstrap-template.yaml" \
    -p "APPLICATION_IMAGE=$APPLICATION_IMAGE" -p "RELEASE_ID=$RELEASE_ID" | \
    oc apply --namespace "$NAMESPACE" -f - >/dev/null
if ! oc wait --namespace "$NAMESPACE" --for=condition=complete "job/$bootstrap_job" \
    --timeout=10m; then
    oc logs --namespace "$NAMESPACE" "job/$bootstrap_job" --all-containers=true --tail=200 || true
    oc delete secret agenthub-bootstrap-credentials --namespace "$NAMESPACE" --ignore-not-found >/dev/null
    die "bootstrap job failed or timed out"
fi
oc delete secret agenthub-bootstrap-credentials --namespace "$NAMESPACE" --ignore-not-found >/dev/null

info "applying restricted-SCC application workloads"
oc process --namespace "$NAMESPACE" -f "$SCRIPT_DIR/agenthub-template.yaml" \
    -p "APPLICATION_IMAGE=$APPLICATION_IMAGE" \
    -p "STATIC_IMAGE=$STATIC_IMAGE" \
    -p "RELEASE_ID=$RELEASE_ID" \
    -p "ROUTE_HOST=$ROUTE_HOST" \
    -p "NAMESPACE=$NAMESPACE" \
    -p "OBJECT_STORE_ENDPOINT=$OBJECT_STORE_ENDPOINT" \
    -p "OBJECT_STORE_BUCKET=$OBJECT_STORE_BUCKET" \
    -p "OBJECT_STORE_REGION=$OBJECT_STORE_REGION" | \
    oc apply --namespace "$NAMESPACE" -f - >/dev/null

for deployment in agenthub-static agenthub-web agenthub-worker-runtime agenthub-worker-ingestion agenthub-worker-eval agenthub-beat
do
    oc rollout restart --namespace "$NAMESPACE" "deployment/$deployment" >/dev/null
    oc rollout status --namespace "$NAMESPACE" "deployment/$deployment" --timeout=10m
done

info "checking HTTPS readiness"
curl --fail --silent --show-error --retry 12 --retry-delay 5 \
    "https://$ROUTE_HOST/v1/health/ready" >/dev/null

if [ "$INSTALL_EXTERNAL_DEMO" = true ]; then
    model_profile_id=$(oc exec --namespace "$NAMESPACE" deployment/agenthub-web -- \
        python manage.py shell -c \
        "from apps.orchestration.models import ModelProfile; print(ModelProfile.objects.get(logical_id='$MODEL_LOGICAL_ID', revision=$MODEL_REVISION).public_id)" | tail -n 1 | tr -d '\r')
    embedding_profile_id=$(oc exec --namespace "$NAMESPACE" deployment/agenthub-web -- \
        python manage.py shell -c \
        "from apps.ingestion.models import EmbeddingProfile; print(EmbeddingProfile.objects.get(logical_id='$EMBEDDING_LOGICAL_ID', revision=$EMBEDDING_REVISION).public_id)" | tail -n 1 | tr -d '\r')
    printf '%s' "$model_profile_id" | grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' || \
        die "could not resolve the configured model profile id"
    printf '%s' "$embedding_profile_id" | grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' || \
        die "could not resolve the configured embedding profile id"
    credential_file="$TMP_DIR/external-demo-credentials.json"
    pod_file="/tmp/external-demo-credentials-$RELEASE_ID.json"
    if oc get secret agenthub-external-demo-credentials --namespace "$NAMESPACE" >/dev/null 2>&1; then
        encoded_credentials=$(oc get secret agenthub-external-demo-credentials \
            --namespace "$NAMESPACE" -o 'jsonpath={.data.credentials\.json}')
        printf '%s' "$encoded_credentials" | base64 -d > "$credential_file"
        oc exec --namespace "$NAMESPACE" -i deployment/agenthub-worker-ingestion -- \
            /bin/sh -c "umask 077; cat > '$pod_file'" < "$credential_file"
    fi
    info "seeding external consumer demo with the configured generic providers"
    oc exec --namespace "$NAMESPACE" deployment/agenthub-worker-ingestion -- \
        python manage.py seed_external_consumer_demo \
        --credentials-file "$pod_file" \
        --model-profile-id "$model_profile_id" \
        --embedding-profile-id "$embedding_profile_id" \
        --api-base http://agenthub-web:8000 \
        --no-print-secrets
    oc exec --namespace "$NAMESPACE" deployment/agenthub-worker-ingestion -- \
        cat "$pod_file" > "$credential_file"
    python3 -c 'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); assert isinstance(value.get("consumers"), dict) and len(value["consumers"]) == 3' "$credential_file"
    oc create secret generic agenthub-external-demo-credentials \
        --namespace "$NAMESPACE" \
        --from-file="credentials.json=$credential_file" \
        --dry-run=client -o yaml | oc apply --namespace "$NAMESPACE" -f - >/dev/null
    oc process --namespace "$NAMESPACE" -f "$SCRIPT_DIR/external-demo-template.yaml" \
        -p "DEMO_IMAGE=$DEMO_IMAGE" -p "DEMO_ROUTE_HOST=$DEMO_ROUTE_HOST" | \
        oc apply --namespace "$NAMESPACE" -f - >/dev/null
    oc rollout restart --namespace "$NAMESPACE" deployment/agenthub-external-demo >/dev/null
    oc rollout status --namespace "$NAMESPACE" deployment/agenthub-external-demo --timeout=10m
    curl --fail --silent --show-error --retry 12 --retry-delay 5 \
        "https://$DEMO_ROUTE_HOST/healthz" >/dev/null
    info "external demo URL: https://$DEMO_ROUTE_HOST"
    info "external demo console username: external-demo-admin"
    info "retrieve the demo password only when needed using the documented Secret command"
fi

info "AgentHub console: https://$ROUTE_HOST/console/"
info "provider profiles: $MODEL_LOGICAL_ID:r$MODEL_REVISION and $EMBEDDING_LOGICAL_ID:r$EMBEDDING_REVISION"
info "installation completed"
