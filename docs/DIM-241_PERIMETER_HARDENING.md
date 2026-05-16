# DIM-241 Perimeter Hardening Runbook

This runbook operationalizes perimeter controls for Hermes Web View + Mission Control API.
It is intended to be executed alongside `docs/DIM-213_DEPLOYMENT.md`.

## 1) Network exposure lockdown

Checklist:

- [ ] No direct public exposure of Mission Control API port `8767`
- [ ] No router port-forward/NAT rule to `8767`
- [ ] Host firewall default deny inbound
- [ ] Firewall allows `8767` only from Pi Tailscale IP on `tailscale0`
- [ ] Non-tailnet traffic to `8767` is denied

Example using `ufw`:

```bash
sudo ufw default deny incoming
sudo ufw allow in on tailscale0 from <pi_tailscale_ip> to any port 8767 proto tcp
sudo ufw deny 8767/tcp
sudo ufw status numbered
```

Verification:

```bash
ss -ltn '( sport = :8767 )'
sudo ufw status | rg 8767
```

## 2) Cloudflare Access gateway path

Checklist:

- [ ] Dashboard served via Cloudflare Tunnel -> `http://127.0.0.1:8767`
- [ ] Cloudflare Access policy enforces identity + MFA
- [ ] Tunnel injects `X-Hermes-Origin-Secret`
- [ ] `DASHBOARD_AUTH_MODE=cloudflare`
- [ ] `DASHBOARD_SHARED_SECRET` matches the tunnel header value

Cloudflared ingress example:

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

## 3) App-level auth/security

Checklist:

- [ ] `ENVIRONMENT=production`
- [ ] `AUTH_MODE=all` (or intentional exception documented)
- [ ] `BEARER_TOKEN` is strong random secret
- [ ] `EXPOSE_DOCS=false`
- [ ] `CORS_ORIGINS` explicit (no wildcard)
- [ ] `/dashboard` and `/static/*` return `401` without Cloudflare headers
- [ ] WebSocket ops stream requires token

Config validation (DIM-241 guardrails):

```bash
./scripts/hermes-mission-control audit
```

Runtime validation:

```bash
./scripts/hermes-mission-control audit --runtime
```

## 4) DIM-237 alignment

Checklist:

- [ ] `MEMORY_INGEST_BACKEND=hindsight`
- [ ] `MEMORY_INGEST_HMAC_SECRET` rotated and synced with Pi sender
- [ ] `MEMORY_INGEST_ALLOWED_SOURCES` restricted to Pi tailnet IP(s)
- [ ] `/api/memory/ingest/health` reports `backend=hindsight` and `ok=true`

Manual health check:

```bash
curl -H "Authorization: Bearer <BEARER_TOKEN>" \
  http://127.0.0.1:8767/api/memory/ingest/health
```

## 5) Autostart + operations

Checklist:

- [ ] Install service using `./scripts/hermes-mission-control install --start`
- [ ] Env file exists at `~/.config/hermes/mission-control.env` with mode `600`
- [ ] User-systemd autostart symlink exists (`default.target.wants`)
- [ ] Linger enabled when required (`sudo loginctl enable-linger $USER`)
- [ ] Rollback + smoke tests documented

Checks:

```bash
./scripts/hermes-mission-control status
ls -l ~/.config/hermes/mission-control.env
ls -l ~/.config/systemd/user/default.target.wants/hermes-mission-control.service
```

## 6) Smoke-test checklist

1. Run `./scripts/hermes-mission-control audit`
2. Run `./scripts/hermes-mission-control audit --runtime`
3. Confirm unauthorized dashboard/static requests are `401`
4. Confirm ingest health shows `backend=hindsight`, `ok=true`
5. Confirm firewall rules still restrict `8767` source scope

## 7) PR evidence checklist (screenshots)

Attach screenshots or terminal captures for:

1. `audit --runtime` passing output
2. unauthorized `/dashboard` and `/static/*` checks returning `401`
3. ingest health response showing `backend=hindsight` + `ok=true`
4. firewall rule snapshot showing restricted `8767`

Suggested artifact location in repo:

- `mission-control-api/docs/screenshots/dim-241/`

## References

- `mission-control-api/docs/DIM-213_DEPLOYMENT.md`
- `mission-control-api/deploy/mission-control.env.example`
- `docs/security/dim-221-control-data-plane-hardening.md`
- `docs/dim-237-pi-hindsight-v2-lite-runbook.md`
