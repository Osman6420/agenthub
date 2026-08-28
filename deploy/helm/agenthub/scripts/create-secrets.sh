#!/bin/sh
set -eu

umask 077

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '==> %s\n' "$*"
}

require_var() {
    name=$1
    eval "value=\${$name-}"
    [ -n "$value" ] || die "$name is required"
    newline='
'
    case "$value" in
        *"$newline"*) die "$name must not contain a newline" ;;
    esac
}

write_env_value() {
    file=$1
    name=$2
    value=$3
    printf '%s=%s\n' "$name" "$value" >> "$file"
}

apply_secret_file() {
    name=$1
    file=$2
    oc create secret generic "$name" \
        --namespace "$NAMESPACE" \
        --from-env-file="$file" \
        --dry-run=client -o yaml | \
        oc apply --namespace "$NAMESPACE" \
            --server-side \
            --field-manager=agenthub-secret-preparer \
            --force-conflicts \
            -f - >/dev/null
}

[ "$#" -eq 1 ] || die "usage: $0 /protected/path/openshift.env"
CONFIG_FILE=$1
[ -f "$CONFIG_FILE" ] && [ -r "$CONFIG_FILE" ] || die "configuration file is not readable"

mode=$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || true)
case "$mode" in
    *00) ;;
    *) die "configuration file must not be readable or writable by group/others (use chmod 600)" ;;
esac

# This file is trusted operator-authored POSIX shell input. Never use a downloaded/untrusted file.
# shellcheck disable=SC1090
. "$CONFIG_FILE"

for name in \
    NAMESPACE DJANGO_SECRET_KEY METRICS_BEARER_TOKEN BOOTSTRAP_ADMIN_PASSWORD \
    DATABASE_URL MIGRATION_DATABASE_URL DATABASE_HOST DATABASE_PORT DATABASE_NAME \
    DATABASE_USER MIGRATION_DATABASE_USER REDIS_URL \
    AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY MODEL_API_KEY EMBEDDING_API_KEY
do
    require_var "$name"
done

command -v oc >/dev/null 2>&1 || die "oc is required"
oc whoami >/dev/null 2>&1 || die "oc is not logged in"
oc get namespace "$NAMESPACE" >/dev/null 2>&1 || die "namespace $NAMESPACE does not exist"
oc auth can-i create secrets --namespace "$NAMESPACE" | grep -qx yes || \
    die "current oc identity cannot create Secrets in $NAMESPACE"
oc auth can-i patch secrets --namespace "$NAMESPACE" | grep -qx yes || \
    die "current oc identity cannot update Secrets in $NAMESPACE"

TMP_DIR=$(mktemp -d)
chmod 700 "$TMP_DIR"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT HUP INT TERM

web_env="$TMP_DIR/web.env"
runtime_env="$TMP_DIR/runtime.env"
ingestion_env="$TMP_DIR/ingestion.env"
beat_env="$TMP_DIR/beat.env"
migration_env="$TMP_DIR/migration.env"
bootstrap_env="$TMP_DIR/bootstrap.env"

write_env_value "$web_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$web_env" DATABASE_URL "$DATABASE_URL"
write_env_value "$web_env" REDIS_URL "$REDIS_URL"
write_env_value "$web_env" METRICS_BEARER_TOKEN "$METRICS_BEARER_TOKEN"
write_env_value "$web_env" MODEL_SECRET_PRIMARY "$MODEL_API_KEY"
write_env_value "$web_env" AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"
write_env_value "$web_env" AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"

write_env_value "$runtime_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$runtime_env" DATABASE_URL "$DATABASE_URL"
write_env_value "$runtime_env" DATABASE_HOST "$DATABASE_HOST"
write_env_value "$runtime_env" DATABASE_PORT "$DATABASE_PORT"
write_env_value "$runtime_env" DATABASE_USER "$DATABASE_USER"
write_env_value "$runtime_env" DATABASE_NAME "$DATABASE_NAME"
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
write_env_value "$migration_env" DATABASE_HOST "$DATABASE_HOST"
write_env_value "$migration_env" DATABASE_PORT "$DATABASE_PORT"
write_env_value "$migration_env" DATABASE_USER "$MIGRATION_DATABASE_USER"
write_env_value "$migration_env" DATABASE_NAME "$DATABASE_NAME"
write_env_value "$migration_env" REDIS_URL "$REDIS_URL"

write_env_value "$bootstrap_env" BOOTSTRAP_ADMIN_PASSWORD "$BOOTSTRAP_ADMIN_PASSWORD"

chmod 600 "$web_env" "$runtime_env" "$ingestion_env" "$beat_env" \
    "$migration_env" "$bootstrap_env"

info "creating or updating namespace Secrets without printing their values"
apply_secret_file agenthub-web-secrets "$web_env"
apply_secret_file agenthub-runtime-secrets "$runtime_env"
apply_secret_file agenthub-ingestion-secrets "$ingestion_env"
apply_secret_file agenthub-beat-secrets "$beat_env"
apply_secret_file agenthub-migration-secrets "$migration_env"
apply_secret_file agenthub-bootstrap-credentials "$bootstrap_env"
info "Secrets are ready in namespace $NAMESPACE"
