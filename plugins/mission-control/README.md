# Mission Control Dashboard Plugin

Mission Control is the custom ops layer for Dima's Hermes deployment.

This plugin is the migration target for the old standalone `/home/dima/hermes-mission-control` dashboard. Upstream `hermes dashboard` remains the canonical shell for core Hermes admin. This plugin only owns ops surfaces that upstream does not provide:

- PC/Pi fleet health
- Hindsight bank review
- Memory ingest observability
- Linear harness operations
- Digest history/generation
- Provider status visibility
- Shared operations stream

Do not add duplicate config, env, sessions, cron, or chat UI here unless a contract explicitly documents an upstream gap.

Implementation contracts live at:

`/home/dima/hermes-mission-control/docs/consolidation/plugin-contracts.md`

## Durable local install

Run from this repository after cloning or after a clean Hermes update:

```bash
python scripts/install_dashboard_plugin.py --hermes-repo ~/.hermes/hermes-agent
```

The installer does two things:

1. Copies the Mission Control plugin into the local Hermes checkout.
2. Copies the bundled readable dashboard theme to `~/.hermes/dashboard-themes/dima-readable.yaml` and activates it with `hermes config set dashboard.theme dima-readable`.

Use `--skip-theme` if you only want the plugin copy. Use `--skip-theme-activation` if you want the theme file installed but do not want the installer to change Hermes config.

The readable theme source is tracked in this repo at:

`themes/dima-readable.yaml`
