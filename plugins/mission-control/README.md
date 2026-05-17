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
