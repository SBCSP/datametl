# DataMETL Helm chart

Deploys the full DataMETL stack (FastAPI backend + arq worker + Next.js frontend + metadata
Postgres + Redis) behind **oauth2-proxy** for **Keycloak / OIDC SSO**, with **pluggable
exposure** (NodePort for an external nginx, or a Kubernetes Ingress).

> **Phase 1 = authentication gate only.** Any user who authenticates via Keycloak gets full
> access. In-app **viewer/operator RBAC** (operator-only SQL execution + migrations) and an
> **audit log** are Phase 2 — oauth2-proxy already forwards the Keycloak token so that's additive.

## Architecture

```
client → HTTPS → external nginx / Ingress (TLS) → entry Service (NodePort|ClusterIP)
        → oauth2-proxy (OIDC → Keycloak)  → frontend :3000
                                              └ middleware.ts rewrites /api/* → backend :8000
                                                                                  → worker, postgres, redis
```

Resource ordering (ArgoCD sync-waves, and init-container waits under plain Helm):
**wave 0** postgres + redis → **wave 1** alembic migrate Job → **wave 2** backend/worker/frontend/oauth2-proxy.

## Prerequisites

- A Keycloak realm + **confidential client** (see below).
- Container images reachable by the cluster (default `ghcr.io/sbcsp/datametl-*`; override
  `image.registry`/`image.namespace`/`image.pullSecrets` for a mirror/Harbor).
- A storage class for the Postgres/Redis PVCs (`postgres.persistence.storageClass`).

## Keycloak setup (one-time)

1. Create a **confidential** client (standard auth-code flow), e.g. `datametl`.
2. Valid redirect URI: `https://<your-host>/oauth2/callback`.
3. Web origins: `https://<your-host>`.
4. Copy the client secret → `oauth2Proxy.oidc.clientSecret` (or your existingSecret).
5. Create realm roles `datametl-viewer` and `datametl-operator` now — unused in Phase 1, wired
   up in Phase 2.

`oauth2Proxy.oidc.issuerUrl` = `https://<keycloak>/realms/<realm>`.

## Install

```bash
# 1. generate the required secrets
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
COOKIE_SECRET=$(openssl rand -base64 32)

# 2. edit values-example-rke2.yaml (or your own), then:
helm install datametl ./deploy/helm/datametl -n datametl --create-namespace \
  -f deploy/helm/datametl/values-example-rke2.yaml \
  --set secrets.encryptionKey="$ENCRYPTION_KEY" \
  --set oauth2Proxy.oidc.cookieSecret="$COOKIE_SECRET" \
  --set oauth2Proxy.oidc.clientSecret="<from-keycloak>" \
  --set postgres.auth.password="<choose-one>"
```

### Production secrets (recommended)

Don't put secrets in values/Git. Pre-create one Secret (e.g. via **External Secrets Operator**)
containing **all** of: `ENCRYPTION_KEY`, `DATABASE_URL`, `REDIS_URL`, `POSTGRES_PASSWORD`,
`OAUTH2_PROXY_CLIENT_SECRET`, `OAUTH2_PROXY_COOKIE_SECRET`. Then set `secrets.existingSecret:
<name>` and omit the inline secret values.

> ⚠️ **The Fernet `ENCRYPTION_KEY` must be durable and versioned.** Losing or rotating it
> without re-encrypting makes every stored DB connection credential **unrecoverable**.

## Exposure options

### A) On-prem: external nginx → NodePort (default)

`service.type: NodePort` (+ optional fixed `service.nodePort`). Point your external HA nginx at
any node IP on that NodePort:

```nginx
server {
  listen 443 ssl;
  server_name datametl.example.com;
  ssl_certificate     /etc/nginx/tls/datametl.crt;
  ssl_certificate_key /etc/nginx/tls/datametl.key;

  location / {
    proxy_pass http://<rke2-node-ip>:30080;   # service.nodePort
    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-Proto https;  # so oauth2-proxy builds https redirects + secure cookies
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Real-IP         $remote_addr;
  }
}
```

`oauth2Proxy.externalUrl` must equal the public URL (`https://datametl.example.com`).

### B) Cloud / in-cluster Ingress

Set `service.type: ClusterIP`, `ingress.enabled: true`, and `ingress.className` /
`ingress.annotations` / `ingress.host` / `ingress.tls` (see `values-example-ingress.yaml`).
Works with nginx-ingress, AWS ALB (`className: alb`), etc.

## ArgoCD

See [`deploy/argocd/datametl-application.yaml`](../../argocd/datametl-application.yaml). Point
the Application at this chart path (Git) or the OCI chart `oci://ghcr.io/sbcsp/charts/datametl`.
Sync-waves order DB → migrate → app automatically.

## Verify

```bash
kubectl -n datametl get pods,jobs,svc
# migrate Job should Complete; backend/worker leave Init (wait-for-schema) once it does.
kubectl -n datametl port-forward svc/datametl-datametl-proxy 8080:80
# open http://localhost:8080 → redirected to Keycloak → after login the app loads;
# DevTools shows only same-origin /api/* calls.
```

## Key values

| Key | Default | Notes |
|---|---|---|
| `image.registry` / `image.namespace` | `ghcr.io` / `sbcsp` | override for a mirror |
| `image.pullSecrets` | `[]` | `[{name: harbor-cred}]` for private registries |
| `worker.replicas` | `2` | scale for large jobs |
| `secrets.existingSecret` | `""` | BYO Secret (ESO); else chart generates one |
| `postgres.enabled` / `redis.enabled` | `true` | `false` → use `*.external.*` |
| `postgres.persistence.storageClass` | `""` | e.g. `longhorn`, `gp3` |
| `oauth2Proxy.oidc.issuerUrl` | `""` | **required** |
| `oauth2Proxy.externalUrl` | `""` | public URL (redirect + cookie) |
| `service.type` | `NodePort` | `NodePort`/`ClusterIP`/`LoadBalancer` |
| `service.nodePort` | `""` | fixed NodePort for the external nginx |
| `ingress.enabled` | `false` | set `true` for cloud Ingress |
