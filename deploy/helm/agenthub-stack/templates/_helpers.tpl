{{- define "agenthub-stack.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 40 | trimSuffix "-" -}}
{{- end -}}

{{- define "agenthub-stack.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 40 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "agenthub-stack.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 40 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 40 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "agenthub-stack.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: {{ include "agenthub-stack.name" . | quote }}
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
app.kubernetes.io/part-of: agenthub-stack
{{- end -}}

{{- define "agenthub-stack.componentLabels" -}}
{{ include "agenthub-stack.labels" .root }}
app.kubernetes.io/component: {{ .component | quote }}
{{- end -}}

{{- define "agenthub-stack.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agenthub-stack.name" .root | quote }}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/component: {{ .component | quote }}
{{- end -}}

{{- define "agenthub-stack.image" -}}
{{- printf "%s@%s" (required (printf "%s.image.repository is required" .name) .image.repository) (required (printf "%s.image.digest is required" .name) .image.digest) -}}
{{- end -}}

{{- define "agenthub-stack.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ .name | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "agenthub-stack.podSecurityContext" -}}
seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "agenthub-stack.containerSecurityContext" -}}
allowPrivilegeEscalation: false
capabilities: { drop: ["ALL"] }
readOnlyRootFilesystem: true
runAsNonRoot: true
{{- end -}}
