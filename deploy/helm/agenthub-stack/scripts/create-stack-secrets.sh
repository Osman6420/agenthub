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

require_url_safe() {
    name=$1
    eval "value=\${$name-}"
    case "$value" in
        *[!A-Za-z0-9._~-]*) die "$name must contain only URL-safe unreserved characters" ;;
    esac
}

require_sql_identifier() {
    name=$1
    eval "value=\${$name-}"
    case "$value" in
        ''|[0-9]*|*[!a-z0-9_]*) die "$name must be a lowercase PostgreSQL identifier" ;;
    esac
    [ "${#value}" -le 63 ] || die "$name is longer than 63 characters"
}

require_dns_name() {
    name=$1
    eval "value=\${$name-}"
    [ "${#value}" -le 253 ] || die "$name is longer than 253 characters"
    printf '%s\n' "$value" | \
        grep -Eq '^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]*[a-z0-9])?$' || \
        die "$name must be a lowercase DNS name"
}

require_min_length() {
    name=$1
    minimum=$2
    eval "value=\${$name-}"
    [ "${#value}" -ge "$minimum" ] || die "$name must be at least $minimum characters"
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
            --field-manager=agenthub-stack-secret-preparer \
            --force-conflicts \
            -f - >/dev/null
}

[ "$#" -eq 1 ] || die "usage: $0 /protected/path/stack.env"
CONFIG_FILE=$1
[ -f "$CONFIG_FILE" ] && [ -r "$CONFIG_FILE" ] || die "configuration file is not readable"
mode=$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || true)
case "$mode" in
    *00) ;;
    *) die "configuration file must not be readable or writable by group/others (use chmod 600)" ;;
esac

# Trusted operator-authored POSIX shell input only.
# shellcheck disable=SC1090
. "$CONFIG_FILE"

for name in \
    NAMESPACE STACK_POSTGRES_HOST STACK_REDIS_HOST \
    STACK_POSTGRES_ADMIN_USER STACK_POSTGRES_ADMIN_PASSWORD STACK_POSTGRES_DATABASE \
    STACK_POSTGRES_MIGRATION_USER STACK_POSTGRES_MIGRATION_PASSWORD \
    STACK_POSTGRES_APPLICATION_USER STACK_POSTGRES_APPLICATION_PASSWORD \
    STACK_REDIS_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD \
    AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
    DJANGO_SECRET_KEY METRICS_BEARER_TOKEN BOOTSTRAP_ADMIN_PASSWORD \
    MODEL_API_KEY EMBEDDING_API_KEY
do
    require_var "$name"
done

for name in STACK_POSTGRES_ADMIN_USER STACK_POSTGRES_DATABASE \
    STACK_POSTGRES_MIGRATION_USER STACK_POSTGRES_APPLICATION_USER
do
    require_sql_identifier "$name"
done

for name in STACK_POSTGRES_MIGRATION_PASSWORD STACK_POSTGRES_APPLICATION_PASSWORD \
    STACK_REDIS_PASSWORD
do
    require_url_safe "$name"
done
require_dns_name STACK_POSTGRES_HOST
require_dns_name STACK_REDIS_HOST
require_min_length MINIO_ROOT_USER 3
require_min_length AWS_ACCESS_KEY_ID 3
for name in STACK_POSTGRES_ADMIN_PASSWORD STACK_POSTGRES_MIGRATION_PASSWORD \
    STACK_POSTGRES_APPLICATION_PASSWORD STACK_REDIS_PASSWORD MINIO_ROOT_PASSWORD AWS_SECRET_ACCESS_KEY
do
    require_min_length "$name" 16
done
require_min_length BOOTSTRAP_ADMIN_PASSWORD 12

[ "$STACK_POSTGRES_ADMIN_USER" != "$STACK_POSTGRES_MIGRATION_USER" ] || \
    die "PostgreSQL admin and migration users must differ"
[ "$STACK_POSTGRES_ADMIN_USER" != "$STACK_POSTGRES_APPLICATION_USER" ] || \
    die "PostgreSQL admin and application users must differ"
[ "$STACK_POSTGRES_MIGRATION_USER" != "$STACK_POSTGRES_APPLICATION_USER" ] || \
    die "PostgreSQL migration and application users must differ"
[ "$MINIO_ROOT_USER" != "$AWS_ACCESS_KEY_ID" ] || \
    die "MinIO root and AgentHub application access keys must differ"

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

postgres_env="$TMP_DIR/postgresql.env"
redis_env="$TMP_DIR/redis.env"
minio_env="$TMP_DIR/minio.env"
web_env="$TMP_DIR/web.env"
runtime_env="$TMP_DIR/runtime.env"
ingestion_env="$TMP_DIR/ingestion.env"
beat_env="$TMP_DIR/beat.env"
migration_env="$TMP_DIR/migration.env"
bootstrap_env="$TMP_DIR/bootstrap.env"

write_env_value "$postgres_env" POSTGRES_USER "$STACK_POSTGRES_ADMIN_USER"
write_env_value "$postgres_env" POSTGRES_PASSWORD "$STACK_POSTGRES_ADMIN_PASSWORD"
write_env_value "$postgres_env" POSTGRES_DB postgres
write_env_value "$postgres_env" AGENTHUB_DATABASE "$STACK_POSTGRES_DATABASE"
write_env_value "$postgres_env" AGENTHUB_MIGRATION_USER "$STACK_POSTGRES_MIGRATION_USER"
write_env_value "$postgres_env" AGENTHUB_MIGRATION_PASSWORD "$STACK_POSTGRES_MIGRATION_PASSWORD"
write_env_value "$postgres_env" AGENTHUB_APPLICATION_USER "$STACK_POSTGRES_APPLICATION_USER"
write_env_value "$postgres_env" AGENTHUB_APPLICATION_PASSWORD "$STACK_POSTGRES_APPLICATION_PASSWORD"

write_env_value "$redis_env" REDIS_PASSWORD "$STACK_REDIS_PASSWORD"
write_env_value "$minio_env" MINIO_ROOT_USER "$MINIO_ROOT_USER"
write_env_value "$minio_env" MINIO_ROOT_PASSWORD "$MINIO_ROOT_PASSWORD"
write_env_value "$minio_env" AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"
write_env_value "$minio_env" AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"

runtime_database_url="postgres://$STACK_POSTGRES_APPLICATION_USER:$STACK_POSTGRES_APPLICATION_PASSWORD@$STACK_POSTGRES_HOST:5432/$STACK_POSTGRES_DATABASE"
migration_database_url="postgres://$STACK_POSTGRES_MIGRATION_USER:$STACK_POSTGRES_MIGRATION_PASSWORD@$STACK_POSTGRES_HOST:5432/$STACK_POSTGRES_DATABASE"
redis_url="redis://:$STACK_REDIS_PASSWORD@$STACK_REDIS_HOST:6379/0"

write_env_value "$web_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$web_env" DATABASE_URL "$runtime_database_url"
write_env_value "$web_env" REDIS_URL "$redis_url"
write_env_value "$web_env" METRICS_BEARER_TOKEN "$METRICS_BEARER_TOKEN"
write_env_value "$web_env" MODEL_SECRET_PRIMARY "$MODEL_API_KEY"
write_env_value "$web_env" AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"
write_env_value "$web_env" AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"

write_env_value "$runtime_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$runtime_env" DATABASE_URL "$runtime_database_url"
write_env_value "$runtime_env" DATABASE_HOST "$STACK_POSTGRES_HOST"
write_env_value "$runtime_env" DATABASE_PORT 5432
write_env_value "$runtime_env" DATABASE_USER "$STACK_POSTGRES_APPLICATION_USER"
write_env_value "$runtime_env" DATABASE_NAME "$STACK_POSTGRES_DATABASE"
write_env_value "$runtime_env" REDIS_URL "$redis_url"
write_env_value "$runtime_env" MODEL_SECRET_PRIMARY "$MODEL_API_KEY"

write_env_value "$ingestion_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$ingestion_env" DATABASE_URL "$runtime_database_url"
write_env_value "$ingestion_env" REDIS_URL "$redis_url"
write_env_value "$ingestion_env" AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"
write_env_value "$ingestion_env" AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"
write_env_value "$ingestion_env" EMBEDDING_SECRET_PRIMARY "$EMBEDDING_API_KEY"

write_env_value "$beat_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$beat_env" DATABASE_URL "$runtime_database_url"
write_env_value "$beat_env" REDIS_URL "$redis_url"

write_env_value "$migration_env" DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
write_env_value "$migration_env" DATABASE_URL "$migration_database_url"
write_env_value "$migration_env" DATABASE_HOST "$STACK_POSTGRES_HOST"
write_env_value "$migration_env" DATABASE_PORT 5432
write_env_value "$migration_env" DATABASE_USER "$STACK_POSTGRES_MIGRATION_USER"
write_env_value "$migration_env" DATABASE_NAME "$STACK_POSTGRES_DATABASE"
write_env_value "$migration_env" REDIS_URL "$redis_url"
write_env_value "$bootstrap_env" BOOTSTRAP_ADMIN_PASSWORD "$BOOTSTRAP_ADMIN_PASSWORD"

chmod 600 "$TMP_DIR"/*.env

info "creating infrastructure and application Secrets without printing values"
apply_secret_file agenthub-stack-postgresql "$postgres_env"
apply_secret_file agenthub-stack-redis "$redis_env"
apply_secret_file agenthub-stack-minio "$minio_env"
apply_secret_file agenthub-web-secrets "$web_env"
apply_secret_file agenthub-runtime-secrets "$runtime_env"
apply_secret_file agenthub-ingestion-secrets "$ingestion_env"
apply_secret_file agenthub-beat-secrets "$beat_env"
apply_secret_file agenthub-migration-secrets "$migration_env"
apply_secret_file agenthub-bootstrap-credentials "$bootstrap_env"
info "stack Secrets are ready in namespace $NAMESPACE"
