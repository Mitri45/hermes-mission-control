# Hermes Dashboard behind Cloudflare Access

## Decision

Expose the native `hermes dashboard` through the existing Cloudflare Access-protected hostname instead of keeping the old standalone Mission Control app public.

Mission Control-specific panels now live inside the native dashboard as the `mission-control` dashboard plugin. The old standalone app on `127.0.0.1:8767` should be treated as legacy once the cutover is complete.

## Security model

Use two layers:

1. Cloudflare Access is the real external authentication boundary.
2. Hermes dashboard's ephemeral in-page session token remains the local API guard for dashboard API calls.

Do not expose `hermes dashboard` directly on a public interface. Keep it bound to loopback:

```bash
hermes dashboard --no-open --port 9119
```

Do not use `--host 0.0.0.0 --insecure` for this deployment. That bypasses Hermes' localhost-first safety posture and can expose config/API-key management surfaces on LAN.

## Cloudflared origin routing

Point the Cloudflare Tunnel origin at the local Hermes dashboard:

```yaml
ingress:
  - hostname: hermes.madeby.dev
    service: http://127.0.0.1:9119
    originRequest:
      httpHostHeader: 127.0.0.1:9119
  - service: http_status:404
```

The `httpHostHeader` override matters. Hermes dashboard validates the `Host` header to defend against DNS rebinding. If cloudflared forwards `Host: hermes.madeby.dev` to a dashboard bound to `127.0.0.1`, Hermes can reject the request with `400 Invalid Host header`.

If using a remotely managed tunnel token instead of a local `config.yml`, set the equivalent ingress service and Host-header override in the Cloudflare dashboard.

## Access policy

Keep Cloudflare Access enabled on the hostname. Recommended posture:

- Application: `hermes.madeby.dev`
- Policy: allow only Dima / trusted identities
- Session duration: short enough to be sane; long enough to avoid constant reauth
- Do not create bypass policies for `/api/*`
- Do not expose a second unauthenticated hostname to `127.0.0.1:9119`

## Cutover steps

1. Confirm dashboard is running locally:

```bash
curl -fsS http://127.0.0.1:9119/api/status
```

2. Confirm Mission Control plugin is installed:

```bash
curl -fsS http://127.0.0.1:9119/api/dashboard/plugins | grep mission-control
```

3. Update the tunnel origin from the legacy standalone app:

```text
old: http://127.0.0.1:8767
new: http://127.0.0.1:9119
```

4. Preserve the Host-header override:

```text
httpHostHeader: 127.0.0.1:9119
```

5. Restart/redeploy cloudflared if using a local config.

6. Verify externally:

```text
https://hermes.madeby.dev/mission-control
```

Expected:

- Cloudflare Access login appears first.
- Dashboard loads after Access auth.
- Theme switcher shows `Dima Readable`.
- Mission Control plugin appears in the sidebar.
- Sensitive API calls work from the loaded dashboard.
- Direct unauthenticated requests to protected API endpoints still fail before Access auth.

## Rollback

Point the tunnel origin back to the old standalone app:

```text
http://127.0.0.1:8767
```

This rollback is temporary. The canonical Mission Control source is now the dashboard plugin package in this repository.

## Notes

The Hermes dashboard itself is not a full identity provider. Its injected token is a same-page API guard, not external login. Cloudflare Access remains mandatory for internet exposure.
