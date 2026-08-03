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
