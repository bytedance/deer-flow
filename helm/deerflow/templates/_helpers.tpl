{{/*
Expand the name of the chart.
*/}}
{{- define "deerflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "deerflow.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "deerflow.labels" -}}
helm.sh/chart: {{ include "deerflow.name" . }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: deerflow
{{- end }}

{{/*
Selector labels for a specific component
*/}}
{{- define "deerflow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "deerflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
