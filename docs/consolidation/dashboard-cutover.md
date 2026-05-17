# Hermes Dashboard Cutover

Status: final consolidation checklist for DIM-365 / DIM-366

## Source of truth

- Runtime shell: upstream `hermes dashboard`
- Mission Control ops panels: `Mitri45/hermes-mission-control` plugin at `plugins/mission-control/dashboard`
- Local Hermes install target: `~/.hermes/hermes-agent/plugins/mission-control`

## Ported panels

The native dashboard plugin now owns these Mission Control-specific surfaces:

- Fleet Health: PC/Pi CPU, memory, disk, temperature, service, Tailscale, Pi telemetry degradation
- Hindsight Bank: health, stats, fact browser, source filters, stale review queue
- Memory Ingest: health, checkpoints, counters, lag, dead-letter samples
- Linear Harness: webhook/config status, sessions, worker list, recent operation events
- Provider Status: configured provider visibility without exposing secrets
- Daily Digest: stats, grouped recent entries, source/instance counts
- Operations: recent bounded feed from Hermes logs/harness-visible event sources

## Retired or delegated surfaces

These old standalone Mission Control pages should not be rebuilt as duplicate dashboard pages:

- Generic sessions archive -> upstream `/sessions`
- Generic cron UI -> upstream `/cron`
- Config editor -> upstream `/config`
- Environment/API keys -> upstream `/env`
- Plugins list -> upstream `/plugins`
- Model/provider picker -> upstream `/models`
- Logs -> upstream `/logs`
- Chat facade -> upstream embedded TUI/chat when enabled; do not carry the old Mission Control chat shim forward
- Old bearer-token browser auth -> upstream dashboard ephemeral session-token auth

Keep the old standalone service only as a temporary fallback until the plugin is verified on the target PC.

## Install / update procedure

From the canonical Mission Control repo:

```bash
git clone --branch dim-359-dashboard-plugin-source git@github.com:Mitri45/hermes-mission-control.git
cd hermes-mission-control
python -m pytest tests/test_dashboard_plugin_scaffold.py -q
python scripts/install_dashboard_plugin.py --hermes-repo ~/.hermes/hermes-agent
```

Then start the dashboard:

```bash
cd ~/.hermes/hermes-agent
hermes dashboard --no-open --port 9119
```

Open:

```text
http://127.0.0.1:9119/mission-control
```

## Verification checklist

- `/api/dashboard/plugins` includes `mission-control`
- `/mission-control` renders inside upstream Hermes dashboard navigation
- Unauthenticated `/api/plugins/mission-control/fleet/status` returns 401
- Authenticated browser requests to plugin endpoints return 200
- Fleet Health shows PC and Pi cards or explicit degraded states
- Hindsight Bank shows health, facts count, and stale candidates
- Provider Status shows configured providers without raw key values
- Memory Ingest shows checkpoints/counters/dead letters without leaking payload secrets beyond bounded diagnostics
- Daily Digest shows recent entries or an empty state
- Linear Harness shows sessions/workers/operations or explicit empty states
- Generic admin pages are accessed through upstream dashboard, not duplicated in the plugin

## Cutover decision

Use upstream `hermes dashboard` as the primary UI once the checklist above passes on the target machine.

After cutover:

1. Stop advertising the standalone Mission Control URL as the main UI.
2. Keep the standalone service disabled unless needed for rollback.
3. Keep Cloudflare Access pointed at the upstream dashboard only after confirming host binding/auth posture. Do not expose `--insecure` dashboard binds to LAN/public networks without a reverse proxy and access control.
4. Preserve the old standalone code until one full verification cycle passes, then archive/remove the overlapping web pages.

## Rollback

If the plugin breaks:

1. Stop the dashboard process.
2. Remove or move `~/.hermes/hermes-agent/plugins/mission-control`.
3. Restart `hermes dashboard` to confirm upstream dashboard still works.
4. Temporarily re-enable the old standalone Mission Control service if needed.

No secrets are stored in this document.
