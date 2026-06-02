{{/* Chart name (overridable via nameOverride is intentionally omitted — single app). */}}
{{- define "datametl.name" -}}
datametl
{{- end -}}

{{- define "datametl.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "datametl.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "datametl.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "datametl.labels" -}}
helm.sh/chart: {{ include "datametl.chart" . }}
app.kubernetes.io/name: {{ include "datametl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}

{{- define "datametl.selectorLabels" -}}
app.kubernetes.io/name: {{ include "datametl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "datametl.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "datametl.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* image: call as (list $root $repo $tag); tag falls back to .Chart.AppVersion. */}}
{{- define "datametl.image" -}}
{{- $root := index . 0 -}}
{{- $repo := index . 1 -}}
{{- $tag := index . 2 -}}
{{- $t := $tag | default $root.Chart.AppVersion -}}
{{- printf "%s/%s/%s:%s" $root.Values.image.registry $root.Values.image.namespace $repo $t -}}
{{- end -}}

{{- define "datametl.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* Name of the Secret env is sourced from (BYO existingSecret, else chart-managed). */}}
{{- define "datametl.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "datametl.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* DATABASE_URL — composed only when the chart manages the Secret (no existingSecret). */}}
{{- define "datametl.databaseUrl" -}}
{{- if .Values.postgres.enabled -}}
{{- printf "postgresql+psycopg://%s:%s@%s-postgres:5432/%s" .Values.postgres.auth.username .Values.postgres.auth.password (include "datametl.fullname" .) .Values.postgres.auth.database -}}
{{- else -}}
{{- printf "postgresql+psycopg://%s:%s@%s:%v/%s" .Values.postgres.external.username .Values.postgres.auth.password .Values.postgres.external.host .Values.postgres.external.port .Values.postgres.external.database -}}
{{- end -}}
{{- end -}}

{{- define "datametl.redisUrl" -}}
{{- if .Values.redis.enabled -}}
{{- printf "redis://%s-redis:6379/0" (include "datametl.fullname" .) -}}
{{- else -}}
{{- .Values.redis.external.url -}}
{{- end -}}
{{- end -}}

{{/* Common app env for backend / worker / migrate. */}}
{{- define "datametl.appEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "datametl.secretName" . }}
      key: DATABASE_URL
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "datametl.secretName" . }}
      key: REDIS_URL
- name: ENCRYPTION_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "datametl.secretName" . }}
      key: ENCRYPTION_KEY
- name: LOG_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: CORS_ORIGINS
  value: {{ .Values.config.corsOrigins | quote }}
{{- end -}}

{{/* initContainer: block until Postgres accepts connections (connectivity only). */}}
{{- define "datametl.initWaitDb" -}}
- name: wait-for-db
  image: {{ include "datametl.image" (list . .Values.backend.repo .Values.backend.tag) }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  command:
    - sh
    - -c
    - >-
      until python -c "import os,psycopg; psycopg.connect(os.environ['DATABASE_URL'].replace('+psycopg',''), connect_timeout=3)";
      do echo "waiting for postgres..."; sleep 3; done
  env:
    {{- include "datametl.appEnv" . | nindent 4 }}
{{- end -}}

{{/* initContainer: block until migrations have applied (alembic_version table exists). */}}
{{- define "datametl.initWaitSchema" -}}
- name: wait-for-schema
  image: {{ include "datametl.image" (list . .Values.backend.repo .Values.backend.tag) }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  command:
    - sh
    - -c
    - >-
      until python -c "import os,psycopg; psycopg.connect(os.environ['DATABASE_URL'].replace('+psycopg',''), connect_timeout=3).execute('select 1 from alembic_version')";
      do echo "waiting for db + migrations..."; sleep 3; done
  env:
    {{- include "datametl.appEnv" . | nindent 4 }}
{{- end -}}
