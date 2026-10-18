{{/*
Common helpers for the DeerFlow chart.
*/}}

{{- define "deer-flow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "deer-flow.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "deer-flow.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "deer-flow.labels" -}}
helm.sh/chart: {{ include "deer-flow.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "deer-flow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "deer-flow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "deer-flow.namespace" -}}
{{- default .Release.Namespace .Values.namespace -}}
{{- end -}}

{{- define "deer-flow.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 0 }}
{{- end }}
{{- end -}}

{{/* Fully-qualified image refs for the three DeerFlow images.
     When `image.registry` is empty, omit the prefix so the ref is
     `deer-flow-gateway:latest` (local-image mode, imagePullPolicy: Never). */}}
{{- define "deer-flow.gatewayImage" -}}
{{- if .Values.image.registry -}}{{- printf "%s/%s:%s" .Values.image.registry .Values.image.gatewayImage .Values.image.tag -}}
{{- else -}}{{- printf "%s:%s" .Values.image.gatewayImage .Values.image.tag -}}{{- end -}}
{{- end -}}

{{- define "deer-flow.frontendImage" -}}
{{- if .Values.image.registry -}}{{- printf "%s/%s:%s" .Values.image.registry .Values.image.frontendImage .Values.image.tag -}}
{{- else -}}{{- printf "%s:%s" .Values.image.frontendImage .Values.image.tag -}}{{- end -}}
{{- end -}}

{{- define "deer-flow.provisionerImage" -}}
{{- if .Values.image.registry -}}{{- printf "%s/%s:%s" .Values.image.registry .Values.image.provisionerImage .Values.image.tag -}}
{{- else -}}{{- printf "%s:%s" .Values.image.provisionerImage .Values.image.tag -}}{{- end -}}
{{- end -}}

{{- define "deer-flow.nginxImage" -}}
{{- printf "%s:%s" .Values.nginx.image.repository .Values.nginx.image.tag -}}
{{- end -}}

{{/* PVC name for the .deer-flow home directory. */}}
{{- define "deer-flow.homePVC" -}}
{{- printf "%s-home" (include "deer-flow.fullname" .) -}}
{{- end -}}

{{/* Name of the Secret holding provider/channel keys. */}}
{{- define "deer-flow.providerSecret" -}}
{{- if .Values.existingSecret -}}{{- .Values.existingSecret -}}
{{- else -}}{{- printf "%s-provider" (include "deer-flow.fullname" .) -}}{{- end -}}
{{- end -}}

{{/* Name of the Secret holding the app secrets (BETTER_AUTH_SECRET,
     DEER_FLOW_INTERNAL_AUTH_TOKEN, AUTH_JWT_SECRET, PROVISIONER_API_KEY,
     DEER_FLOW_CREDENTIALS_KEY).
     `existingAppSecret` points every consumer (gateway, frontend,
     provisioner) at a user-managed Secret instead and skips generating one;
     it must carry PROVISIONER_API_KEY while the provisioner is enabled and
     AUTH_JWT_SECRET for more than one gateway instance. */}}
{{- define "deer-flow.appSecret" -}}
{{- if .Values.existingAppSecret -}}{{- .Values.existingAppSecret -}}
{{- else -}}{{- printf "%s-app" (include "deer-flow.fullname" .) -}}{{- end -}}
{{- end -}}

{{/* "true" when more than one gateway instance shares the database. An explicit
     boolean `gateway.multiInstance` wins -- set it before scaling with
     `kubectl scale` or an HPA, which change the replica count without a Helm
     upgrade -- otherwise it is derived from `gateway.replicas`. */}}
{{- define "deer-flow.gatewayMultiInstance" -}}
{{- if kindIs "invalid" .Values.gateway.multiInstance -}}
{{- gt (int .Values.gateway.replicas) 1 -}}
{{- else -}}
{{- eq (toString .Values.gateway.multiInstance | lower) "true" -}}
{{- end -}}
{{- end -}}

{{/* PodDisruptionBudget minAvailable as Kubernetes accepts it: a positive
     integer or a percentage string such as "50%". Takes a dict with `value`
     (the raw values entry; unset falls back to 1) and `key` (the values path,
     named in the error). `int` on "50%" is 0 -- a budget that protects
     nothing -- so a YAML number renders as an integer, a digit string from
     --set-string becomes that integer, a percentage is preserved quoted, and
     0, "0%", more than 100% or anything else fails the render. Anything that
     is not a plain Go number is normalized with toString before the string
     branches: Helm 3.18.0 loads YAML numbers as json.Number, whose kind is
     "string" but which regexMatch and friends reject at argument validation,
     so the unoverridden default would otherwise fail every multi-replica
     render on that release. */}}
{{- define "deer-flow.pdbMinAvailable" -}}
{{- $raw := .value -}}
{{- if kindIs "invalid" $raw -}}{{- $raw = 1 -}}{{- end -}}
{{- $hint := printf "%s must be a positive integer or a percentage such as \"50%%\" (got %v); a budget of 0 protects nothing, so set %s to false instead" .key $raw (replace ".minAvailable" ".enabled" .key) -}}
{{- if or (kindIs "float64" $raw) (kindIs "int64" $raw) (kindIs "int" $raw) -}}
{{- if or (lt (int $raw) 1) (ne (float64 (int $raw)) (float64 $raw)) -}}{{- fail $hint -}}{{- end -}}
{{- int $raw -}}
{{- else -}}
{{- $text := toString $raw -}}
{{- if regexMatch "^[0-9]+$" $text -}}
{{- if lt (atoi $text) 1 -}}{{- fail $hint -}}{{- end -}}
{{- atoi $text -}}
{{- else if regexMatch "^[0-9]+%$" $text -}}
{{- $percent := atoi (trimSuffix "%" $text) -}}
{{- if or (lt $percent 1) (gt $percent 100) -}}{{- fail $hint -}}{{- end -}}
{{- $text | quote -}}
{{- else -}}
{{- fail $hint -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Name of the postgres StatefulSet/Service. */}}
{{- define "deer-flow.postgresFullname" -}}
{{- printf "%s-postgres" (include "deer-flow.fullname" .) -}}
{{- end -}}

{{/* Name of the Secret holding DATABASE_URL (and, in bundled mode, the
     postgres superuser password). Resolution order:
       1. postgresql.external.existingSecret (user-managed, key=database-url)
       2. postgresql.existingSecret          (user-managed, bundled image)
       3. chart-managed secret `<release>-postgres`
     Only #3 is created by this chart; #1/#2 must exist already. */}}
{{- define "deer-flow.databaseUrlSecret" -}}
{{- if .Values.postgresql.external.existingSecret -}}{{- .Values.postgresql.external.existingSecret -}}
{{- else if .Values.postgresql.existingSecret -}}{{- .Values.postgresql.existingSecret -}}
{{- else -}}{{- include "deer-flow.postgresFullname" . -}}{{- end -}}
{{- end -}}

{{/* Name of the redis StatefulSet/Service. */}}
{{- define "deer-flow.redisFullname" -}}
{{- printf "%s-redis" (include "deer-flow.fullname" .) -}}
{{- end -}}

{{/* Name of the Secret holding the redis stream-bridge URL (key `redis-url`,
     plus `redis-password` in bundled mode when a password is set). Resolution:
       1. redis.external.existingSecret (user-managed, key=redis-url)
       2. redis.existingSecret          (user-managed, bundled image)
       3. chart-managed secret `<release>-redis`
     Only #3 is created by this chart; #1/#2 must exist already. */}}
{{- define "deer-flow.redisUrlSecret" -}}
{{- if .Values.redis.external.existingSecret -}}{{- .Values.redis.external.existingSecret -}}
{{- else if .Values.redis.existingSecret -}}{{- .Values.redis.existingSecret -}}
{{- else -}}{{- include "deer-flow.redisFullname" . -}}{{- end -}}
{{- end -}}

{{/* Whether any redis stream-bridge backend is configured (bundled StatefulSet,
     external URL, or a user-managed Secret). Drives the env injection in the
     gateway deployment. */}}
{{- define "deer-flow.redisConfigured" -}}
{{- or .Values.redis.enabled .Values.redis.external.redisUrl .Values.redis.external.existingSecret .Values.redis.existingSecret -}}
{{- end -}}

{{/* SHA256 checksums of the ConfigMaps. Mount these as pod-template
     annotations: ConfigMaps mounted via subPath do NOT receive live updates,
     so a `helm upgrade` that only changes a ConfigMap would leave pods on stale
     config. A checksum annotation makes any content change alter the pod spec,
     which triggers a rolling restart. */}}
{{- define "deer-flow.configChecksum" -}}
{{- include (print $.Template.BasePath "/configmap-config.yaml") . | sha256sum -}}
{{- end -}}

{{- define "deer-flow.extensionsChecksum" -}}
{{- include (print $.Template.BasePath "/configmap-extensions.yaml") . | sha256sum -}}
{{- end -}}

{{- define "deer-flow.nginxChecksum" -}}
{{- include (print $.Template.BasePath "/configmap-nginx.yaml") . | sha256sum -}}
{{- end -}}

{{/* Percent-encode a string for safe interpolation into a URL userinfo
     (password) segment of a DSN. Sprig lacks urlqueryescape, and
     regexReplaceAllLiteral treats `replacement` as a regex template so chars
     like `[`, `]`, `?` break it - so we chain plain `replace` calls instead.
     `%` is encoded first to avoid double-encoding the percent signs emitted
     for the other characters. Covers the URL-special chars a managed-DB
     password might contain (`@ : / # ? % [ ]` and space). */}}
{{- define "deer-flow.urlEscape" -}}
{{- $s := . -}}
{{- $s = replace "%" "%25" $s -}}
{{- $s = replace "@" "%40" $s -}}
{{- $s = replace ":" "%3A" $s -}}
{{- $s = replace "/" "%2F" $s -}}
{{- $s = replace "#" "%23" $s -}}
{{- $s = replace "?" "%3F" $s -}}
{{- $s = replace "[" "%5B" $s -}}
{{- $s = replace "]" "%5D" $s -}}
{{- $s = replace " " "%20" $s -}}
{{- $s -}}
{{- end -}}
