# DIM-213 Deployment Runbook (Hermes Web View)

This runbook deploys Hermes Web View (`/dashboard`) and Mission Control API with:

- secure access defaults,
- DIM-237-compatible memory ingest (`hindsight` backend),
- systemd user-service autostart.

## 1) Preflight

From repo root:

```bash
source venv/bin/activate
cd mission-control-api/frontend
npm ci
npm run build
cd ../..
```

## 2) Configure production env

Copy and edit:

```bash
mkdir -p ~/.config/hermes
cp mission-control-api/deploy/mission-control.env.example ~/.config/hermes/mission-control.env
chmod 600 ~/.config/hermes/mission-control.env
```

Minimum required values:

- `ENVIRONMENT=production`
- `AUTH_MODE=all`
- `BEARER_TOKEN=<strong random token>`
- `CORS_ORIGINS=["https://<your-web-origin>"]`
- `DASHBOARD_AUTH_MODE=cloudflare`
- `DASHBOARD_SHARED_SECRET=<strong random secret>`
- `MEMORY_INGEST_BACKEND=hindsight`
- `MEMORY_INGEST_HMAC_SECRET=<shared ingest secret>`
- `MEMORY_INGEST_ALLOWED_SOURCES=["<pi tailscale ip>"]`
- `MEMORY_INGEST_HINDSIGHT_BASE_URL=http://127.0.0.1:9177`

The service helper refuses `start`/`restart` while DIM-241 hardening checks fail.
Run config checks before install/start:

```bash
./scripts/hermes-mission-control audit
```

## 3) Install and enable systemd autostart

```bash
./scripts/hermes-mission-control install --start
```

This creates and enables:

- `~/.config/systemd/user/hermes-mission-control.service`

Verify:

```bash
./scripts/hermes-mission-control status
journalctl --user -u hermes-mission-control -f
```

To keep user services alive after logout:

```bash
sudo loginctl enable-linger "$USER"
```

## 4) Access control guidance

Treat Web View as internal ops surface:

1. Put it behind private network + access gateway (Tailscale + Cloudflare Access).
2. Do not expose `8767` via router port-forwarding.
3. Keep docs disabled in production (`EXPOSE_DOCS=false`).
4. Keep CORS explicit (no `*` in production).

## 5) Cloudflare strict dashboard gate

When `DASHBOARD_AUTH_MODE=cloudflare`, the app blocks `/dashboard` and `/static/*` unless:

- Cloudflare Access headers are present (`CF-Access-Authenticated-User-Email` or Access JWT/service-token headers), and
- `X-Hermes-Origin-Secret` matches `DASHBOARD_SHARED_SECRET` (when configured).

Example `cloudflared` ingress with origin header:

```yaml
tunnel: hermes-web
credentials-file: /etc/cloudflared/<tunnel-id>.json
ingress:
  - hostname: hermes.example.com
    service: http://127.0.0.1:8767
    originRequest:
      headers:
        X-Hermes-Origin-Secret: "<same DASHBOARD_SHARED_SECRET>"
  - service: http_status:404
```

Cloudflare Access policy should require your identity + MFA.

## 6) Tailscale perimeter for ingest

Allow only Pi tailnet IP to port `8767` at host firewall level. Deny everything else.

`ufw` example (replace IP/interface for your host):

```bash
sudo ufw default deny incoming
sudo ufw allow in on tailscale0 from <pi_tailscale_ip> to any port 8767 proto tcp
sudo ufw deny 8767/tcp
sudo ufw status numbered
```

Quick checks:

```bash
ss -ltn '( sport = :8767 )'
sudo ufw status | rg 8767
```

Also verify there is no router/NAT port-forward rule to `8767`.

## 7) Dashboard token bootstrap (AUTH_MODE=all)

When `AUTH_MODE=all`, API reads require bearer auth.

Open dashboard once with hash token bootstrap:

```text
https://<host>/dashboard#token=<BEARER_TOKEN>
```

The token is stored in browser `localStorage` and removed from URL after bootstrapping.
To clear it:

```text
https://<host>/dashboard#clearToken=1
```

## 8) DIM-237 alignment checks

Confirm ingest backend and health after deploy:

```bash
curl -H "Authorization: Bearer <BEARER_TOKEN>" \
  http://127.0.0.1:8767/api/memory/ingest/health
```

Expected:

- `"backend": "hindsight"`
- `"ok": true`

Run runtime hardening checks (service must already be running):

```bash
./scripts/hermes-mission-control audit --runtime
```

## 9) Evidence capture (for PR/review)

Capture and attach screenshots/log snippets for:

1. Cloudflare Access gate (unauthorized request to `/dashboard` or `/static/*` -> `401`)
2. `audit --runtime` passing output
3. `/api/memory/ingest/health` showing `backend=hindsight` and `ok=true`
4. Firewall status (`ufw status` or equivalent) showing restricted `8767` policy

Recommended path in repo for artifacts:

- `mission-control-api/docs/screenshots/dim-241/`

## 10) Rollback

1. Stop service:
   `./scripts/hermes-mission-control stop`
2. Restore previous env file values (or previous git revision).
3. Restart:
   `./scripts/hermes-mission-control restart`
