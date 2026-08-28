{{- define "agenthub.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agenthub.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 40 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "agenthub.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 40 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 40 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "agenthub.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: {{ include "agenthub.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/version: {{ required "releaseId is required" .Values.releaseId | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
app.kubernetes.io/part-of: agenthub
{{- end -}}

{{- define "agenthub.componentLabels" -}}
{{ include "agenthub.labels" .root }}
app.kubernetes.io/component: {{ .component | quote }}
{{- end -}}

{{- define "agenthub.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agenthub.name" .root | quote }}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/component: {{ .component | quote }}
{{- end -}}

{{- define "agenthub.applicationImage" -}}
{{- printf "%s@%s" (required "images.application.repository is required" .Values.images.application.repository) (required "images.application.digest is required" .Values.images.application.digest) -}}
{{- end -}}

{{- define "agenthub.staticImage" -}}
{{- printf "%s@%s" (required "images.static.repository is required" .Values.images.static.repository) (required "images.static.digest is required" .Values.images.static.digest) -}}
{{- end -}}

{{- define "agenthub.databaseProbeImage" -}}
{{- printf "%s@%s" (required "databaseInitialization.probeImage.repository is required" .Values.databaseInitialization.probeImage.repository) (required "databaseInitialization.probeImage.digest is required" .Values.databaseInitialization.probeImage.digest) -}}
{{- end -}}

{{- define "agenthub.demoImage" -}}
{{- printf "%s@%s" (required "externalDemo.image.repository is required when enabled" .Values.externalDemo.image.repository) (required "externalDemo.image.digest is required when enabled" .Values.externalDemo.image.digest) -}}
{{- end -}}

{{- define "agenthub.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ .name | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "agenthub.podSecurityContext" -}}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "agenthub.containerSecurityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]
readOnlyRootFilesystem: true
runAsNonRoot: true
{{- end -}}

{{- define "agenthub.configData" -}}
DJANGO_SETTINGS_MODULE: config.settings.production
DJANGO_ALLOWED_HOSTS: {{ printf "%s,%s-web,%s-web.%s.svc" (required "route.host is required" .Values.route.host) (include "agenthub.fullname" .) (include "agenthub.fullname" .) .Release.Namespace | quote }}
AGENTHUB_STATIC_RELEASE_ID: {{ required "releaseId is required" .Values.releaseId | quote }}
DJANGO_STATIC_URL: {{ printf "/static/%s/" .Values.releaseId | quote }}
DJANGO_SECURE_SSL_REDIRECT: "true"
RUNTIME_MODEL_PROVIDER: apps.orchestration.providers.OpenAICompatibleModelProvider
RUNTIME_EMBEDDING_PROVIDER: apps.ingestion.embedding.OpenAICompatibleEmbeddingClient
RUNTIME_RETRIEVAL_PROVIDER: apps.retrieval.providers.PgvectorRetrievalProvider
OBJECT_STORE_ENDPOINT: {{ required "objectStore.endpoint is required" .Values.objectStore.endpoint | quote }}
OBJECT_STORE_BUCKET: {{ required "objectStore.bucket is required" .Values.objectStore.bucket | quote }}
OBJECT_STORE_REGION: {{ .Values.objectStore.region | quote }}
DOCUMENTS_OBJECT_STORE_BACKEND: s3
MCP_ENABLED: "false"
METRICS_ENABLED: "true"
OTEL_SERVICE_NAME: agenthub
OTEL_EXPORTER_OTLP_ENDPOINT: ""
OTEL_EXPORTER_OTLP_ALLOWED_HOSTS: ""
PYTHON_NODE_RUNTIME_ENABLED: "false"
TOOL_ADAPTER: deterministic
{{- end -}}

{{- define "agenthub.providerEnv" -}}
- {name: PLATFORM_ACTOR, value: {{ .Values.bootstrap.actor | quote }}}
- {name: MODEL_LOGICAL_ID, value: {{ .Values.provider.model.logicalId | quote }}}
- {name: MODEL_REVISION, value: {{ .Values.provider.model.revision | quote }}}
- {name: MODEL_HOST, value: {{ .Values.provider.model.host | quote }}}
- {name: MODEL_PORT, value: {{ .Values.provider.model.port | quote }}}
- {name: MODEL_PATH, value: {{ .Values.provider.model.path | quote }}}
- {name: MODEL_NAME, value: {{ .Values.provider.model.name | quote }}}
- {name: EMBEDDING_LOGICAL_ID, value: {{ .Values.provider.embedding.logicalId | quote }}}
- {name: EMBEDDING_REVISION, value: {{ .Values.provider.embedding.revision | quote }}}
- {name: EMBEDDING_HOST, value: {{ .Values.provider.embedding.host | quote }}}
- {name: EMBEDDING_PORT, value: {{ .Values.provider.embedding.port | quote }}}
- {name: EMBEDDING_PATH, value: {{ .Values.provider.embedding.path | quote }}}
- {name: EMBEDDING_NAME, value: {{ .Values.provider.embedding.name | quote }}}
- {name: EMBEDDING_DIMENSIONS, value: {{ .Values.provider.embedding.dimensions | quote }}}
- {name: EMBEDDING_INDEX_TYPE, value: {{ .Values.provider.embedding.indexType | quote }}}
{{- end -}}

{{- define "agenthub.hookCommonEnv" -}}
- {name: DJANGO_SETTINGS_MODULE, value: config.settings.production}
- {name: DJANGO_ALLOWED_HOSTS, value: {{ printf "%s,%s-web,%s-web.%s.svc" .Values.route.host (include "agenthub.fullname" .) (include "agenthub.fullname" .) .Release.Namespace | quote }}}
- {name: AGENTHUB_STATIC_RELEASE_ID, value: {{ .Values.releaseId | quote }}}
- {name: DJANGO_STATIC_URL, value: {{ printf "/static/%s/" .Values.releaseId | quote }}}
- {name: DJANGO_SECURE_SSL_REDIRECT, value: "true"}
- {name: RUNTIME_MODEL_PROVIDER, value: apps.orchestration.providers.OpenAICompatibleModelProvider}
- {name: RUNTIME_EMBEDDING_PROVIDER, value: apps.ingestion.embedding.OpenAICompatibleEmbeddingClient}
- {name: RUNTIME_RETRIEVAL_PROVIDER, value: apps.retrieval.providers.PgvectorRetrievalProvider}
- {name: OBJECT_STORE_ENDPOINT, value: {{ .Values.objectStore.endpoint | quote }}}
- {name: OBJECT_STORE_BUCKET, value: {{ .Values.objectStore.bucket | quote }}}
- {name: OBJECT_STORE_REGION, value: {{ .Values.objectStore.region | quote }}}
- {name: DOCUMENTS_OBJECT_STORE_BACKEND, value: s3}
- {name: MCP_ENABLED, value: "false"}
- {name: METRICS_ENABLED, value: "true"}
- {name: PYTHON_NODE_RUNTIME_ENABLED, value: "false"}
- {name: TOOL_ADAPTER, value: deterministic}
{{- end -}}

{{- define "agenthub.waitForPostgresInit" -}}
- name: wait-for-postgres
  image: {{ include "agenthub.databaseProbeImage" .root | quote }}
  imagePullPolicy: {{ .root.Values.databaseInitialization.probeImage.pullPolicy }}
  command: ["/bin/sh", "-ec"]
  args:
    - |
      export PGHOST="${DATABASE_HOST:?DATABASE_HOST is required}"
      export PGPORT="${DATABASE_PORT:-5432}"
      export PGUSER="${DATABASE_USER:?DATABASE_USER is required}"
      export PGDATABASE="${DATABASE_NAME:?DATABASE_NAME is required}"
      deadline=$(( $(date +%s) + {{ .root.Values.databaseInitialization.timeoutSeconds }} ))
      until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE"; do
        echo "waiting for postgres"
        if [ "$(date +%s)" -ge "$deadline" ]; then
          echo "timed out waiting for postgres" >&2
          exit 1
        fi
        sleep 3
      done
  envFrom:
    - secretRef: {name: {{ .secretName | quote }}}
  env:
    - {name: HOME, value: /tmp}
  resources:
    {{- toYaml .root.Values.hookResources.resources | nindent 4 }}
  securityContext:
    {{- include "agenthub.containerSecurityContext" .root | nindent 4 }}
  volumeMounts: [{name: tmp, mountPath: /tmp}]
{{- end -}}

{{- define "agenthub.waitForMigrationsInit" -}}
- name: wait-for-migrations
  image: {{ include "agenthub.applicationImage" . | quote }}
  imagePullPolicy: {{ .Values.images.application.pullPolicy }}
  command: ["/bin/sh", "-ec"]
  args:
    - |
      deadline=$(( $(date +%s) + {{ .Values.databaseInitialization.timeoutSeconds }} ))
      while [ "$(date +%s)" -lt "$deadline" ]; do
        if python - <<'PY'
      import os
      os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
      import django
      django.setup()
      from django.db import connection
      from django.db.migrations.executor import MigrationExecutor
      executor = MigrationExecutor(connection)
      raise SystemExit(1 if executor.migration_plan(executor.loader.graph.leaf_nodes()) else 0)
      PY
        then
          echo "database migrations are ready"
          exit 0
        fi
        echo "waiting for database migrations"
        sleep 5
      done
      echo "timed out waiting for database migrations" >&2
      exit 1
  envFrom:
    - secretRef: {name: {{ .Values.existingSecrets.runtime | quote }}}
  env:
    {{- include "agenthub.hookCommonEnv" . | nindent 4 }}
    - {name: HOME, value: /tmp}
  resources:
    {{- toYaml .Values.hookResources.resources | nindent 4 }}
  securityContext:
    {{- include "agenthub.containerSecurityContext" . | nindent 4 }}
  volumeMounts: [{name: tmp, mountPath: /tmp}]
{{- end -}}

{{- define "agenthub.deploymentDatabaseGateInit" -}}
- name: wait-for-database-bootstrap
  image: {{ include "agenthub.applicationImage" .root | quote }}
  imagePullPolicy: {{ .root.Values.images.application.pullPolicy }}
  command: ["/bin/sh", "-ec"]
  args:
    - |
      deadline=$(( $(date +%s) + {{ .root.Values.databaseInitialization.timeoutSeconds }} ))
      while [ "$(date +%s)" -lt "$deadline" ]; do
        set +e
        output="$(python manage.py ensure_deployment_profiles --check-only 2>&1)"
        status=$?
        set -e
        case "$status" in
          0)
            echo "$output"
            exit 0
            ;;
          3)
            echo "$output"
            sleep 5
            ;;
          *)
            echo "database bootstrap configuration is invalid: $output" >&2
            exit "$status"
            ;;
        esac
      done
      echo "timed out waiting for database migrations/bootstrap" >&2
      exit 1
  envFrom:
    - configMapRef: {name: {{ include "agenthub.fullname" .root }}-config}
    - secretRef: {name: {{ .secretName | quote }}}
  env:
    {{- include "agenthub.providerEnv" .root | nindent 4 }}
    - {name: HOME, value: /tmp}
  resources:
    {{- toYaml .root.Values.hookResources.resources | nindent 4 }}
  securityContext:
    {{- include "agenthub.containerSecurityContext" .root | nindent 4 }}
  volumeMounts: [{name: tmp, mountPath: /tmp}]
{{- end -}}
