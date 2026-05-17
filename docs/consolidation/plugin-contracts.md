# Mission Control Plugin Contracts

Status: draft contract for DIM-358 / dashboard consolidation
Source repos inspected:
- Mission Control: `/home/dima/hermes-mission-control`
- Upstream Hermes: `/home/dima/.hermes/hermes-agent`

Goal: make the migration boundary explicit before porting Mission Control panels into the upstream `hermes dashboard`. Upstream Hermes remains the shell of record. Mission Control-only capabilities move into dashboard plugin APIs under `/api/plugins/mission-control/...`; overlapping config/session/cron/chat UI is removed or hidden after equivalent upstream coverage is verified.

## Baseline plugin conventions

Use the upstream Kanban dashboard plugin as the implementation template:
- Frontend tab is declared by `plugins/<plugin>/dashboard/manifest.json` with `tab.path`, `entry`, `css`, and optional `api`.
- Backend plugin routes are mounted by the Hermes dashboard under `/api/plugins/<plugin-name>/...`.
- HTTP auth uses the upstream dashboard session token middleware in `hermes_cli/web_server.py`: all non-public `/api/...` routes require the injected dashboard session token via `X-Hermes-Session-Token` or the legacy Authorization bearer header.
- Plugin WebSockets must authenticate explicitly because browsers cannot set arbitrary upgrade headers consistently. Follow the Kanban pattern: require `?token=<dashboard-session-token>` unless the shared plugin SDK grows a standard subprotocol helper.
- Do not carry Mission Control's bearer/cloudflare auth model into upstream plugin code except where a remote Pi/peer origin needs a separate service-to-service secret.

Recommended physical target:
- One upstream plugin family first: `plugins/mission-control/dashboard/*`
- One manifest tab at `/mission-control` with internal subnavigation, unless later plugin SDK work makes multiple tabs cheaper.
- API prefix: `/api/plugins/mission-control/...`

## Mission Control route/page disposition

| Mission Control route/page | Source files | Disposition | Target / notes |
| --- | --- | --- | --- |
| `/dashboard/` (landing dashboard) | `frontend/src/router.tsx`, `frontend/src/routes/dashboard.tsx`, `app/api/status.py`, `app/api/harness.py`, `app/api/cron.py`, `app/api/digest.py` | MERGE | Merge useful ops cards into `/mission-control` landing. Fleet/system cards are PORT via Fleet Health. Digest and harness summary cards can deep-link to their plugin sections. Do not recreate a second full dashboard shell. |
| `/dashboard/cron` | `frontend/src/routes/cron.tsx`, `app/api/cron.py`, `app/services/cron_service.py` | DELETE/HIDE after review | Upstream Hermes dashboard already has Cron. Keep only if Mission Control's pause/resume/run/retry/log controls for PC/Pi jobs are not available upstream; if kept, make it a small `cron-ops` section rather than a top-level duplicate page. |
| `/dashboard/digest` | `frontend/src/routes/digest.tsx`, `app/api/digest.py`, `app/services/digest_service.py` | PORT | Port to Mission Control plugin section `/digest` or `/mission-control/digest`; API under `/api/plugins/mission-control/digest`. |
| `/dashboard/sessions` | `frontend/src/routes/sessions.tsx`, `frontend/src/components/chatFoundation.tsx`, `app/api/harness.py`, `app/api/chat.py` | PARTIAL PORT + DELETE | Port Linear/non-Hermes worker session controls to `/linear-harness`. Delete generic Hermes session archive duplication and the chat facade after upstream `/sessions` and `hermes dashboard --tui` are verified. |
| `/dashboard/operations` | `frontend/src/routes/operations.tsx`, `app/api/websocket.py`, `app/services/websocket_manager.py` | PORT/MERGE | Port as a shared operations stream used by `/linear-harness` and `/mission-control`. Target WebSocket `/api/plugins/mission-control/operations/stream` or `/api/plugins/mission-control/harness/events`. |
| `/dashboard/memory` | `frontend/src/routes/memory.tsx`, `app/api/hindsight_bank.py`, `app/api/memory_ingest.py`, `app/services/hindsight_bank_service.py`, `app/services/memory_ingest_service.py` | PORT | Port Hindsight Bank manager to `/hindsight`; include Memory Ingest observability as a sub-section unless it grows into a separate plugin. Do not duplicate upstream generic memory provider configuration. |
| `/dashboard/providers` | `frontend/src/routes/providers.tsx`, `app/api/provider_status.py`, `app/services/provider_status_service.py` | PORT | Port to `/provider-status` or a Models-adjacent plugin slot if upstream supports slots. Read-only operational visibility only; no secret editing. |
| Header settings button | `frontend/src/components/shell.tsx` | DELETE | It is currently a button, not a routed page. Upstream dashboard owns config/settings/env. |
| Chat facade embedded in Sessions | `frontend/src/components/chatFoundation.tsx`, `app/api/chat.py`, `app/services/chat_service.py` | DELETE | `ChatService` expects `scripts/mission_control_chat_turn.py` under the Mission Control repo root; that runner is not present in inspected files. Prefer upstream embedded TUI chat. |
| API-only `/api/config` | `app/api/config.py`, `app/services/config_service.py` | DELETE/HIDE | Upstream `/config` and `/env` own configuration. Do not expose duplicate config writes in plugin. |
| API-only `/api/tokens` | `app/api/tokens.py`, `app/services/token_service.py` | MERGE/DELETE | Upstream analytics/models/logging may already expose usage. Only port if a later audit finds unique token aggregation that is not present upstream. |
| API-only `/api/workers` | `app/api/workers.py`, `app/services/harness_service.py` | PORT as part of Linear Harness | Use in `/linear-harness` if it represents non-Hermes/Linear harness worker processes. |
| API-only `/api/memory` | `app/api/memory.py`, `app/services/memory_service.py` | DELETE/HIDE | Superseded by Hindsight Bank for useful memory review and upstream memory provider config for core Hermes memory. |
| API-only `/api/status/health` | `app/api/status.py` | KEEP only as legacy standalone health | In upstream plugin, replace with plugin health endpoint `/api/plugins/mission-control/health`. |
| API-only `/api/memory/ingest` | `app/api/memory_ingest.py` | PORT with special auth | Keep service-to-service ingest endpoint if Pi replication still posts to it. In upstream dashboard this must remain distinct from browser dashboard session auth; see Memory Ingest contract. |

## Contract: Mission Control / Fleet Health landing

Plugin name:
- `mission-control` initially; component/section name `Fleet Health`.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/dashboard.tsx`, `frontend/src/components/shell.tsx` status strip.
- Backend routes: `app/api/status.py`, plus summary reads from `app/api/harness.py`, `app/api/cron.py`, and `app/api/digest.py` currently used by landing cards.
- Services: `app/services/system_monitor.py`, `app/services/harness_service.py`, `app/services/cron_service.py`, `app/services/digest_service.py`.

Target Hermes dashboard route:
- Primary plugin tab: `/mission-control`.
- If split later: `/fleet-health`.

Target API path:
- `GET /api/plugins/mission-control/status?instance=all|pc|pi`
- `GET /api/plugins/mission-control/summary` for landing rollups, if separate from status.
- `GET /api/plugins/mission-control/health` for plugin backend readiness.

Auth model:
- Dashboard session token for browser reads.
- No write operations.
- Any remote Pi status fetch remains server-side; do not expose remote credentials to the browser.

WebSocket needs:
- None required for first port. Poll every 15-30 seconds as current UI does.
- Optional later: subscribe to shared operations stream for freshness events, but Fleet Health must work with polling only.

Read operations:
- Read local PC CPU, memory, disk, temperature, services, Tailscale info, timestamp.
- Read Pi status via configured Pi status source, preserving `instance=pi` and `instance=all` behavior.
- Read summarized harness/webhook health for top-level Pi connectivity.

Write operations:
- None.

Acceptance checks:
- `/mission-control` loads inside upstream `hermes dashboard` without modifying dashboard core routes.
- PC CPU/memory/disk/temp/service/Tailscale state renders.
- Pi telemetry renders when configured and degrades clearly when unavailable/stale.
- Instance filter `all|pc|pi` works.
- Unauthenticated request to `/api/plugins/mission-control/status` returns 401.
- No secrets, bearer tokens, or raw environment values are rendered.

## Contract: Hindsight Bank

Plugin name:
- `mission-control` section `Hindsight Bank`; split candidate `hindsight-bank`.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/memory.tsx`.
- Backend routes: `app/api/hindsight_bank.py`.
- Services: `app/services/hindsight_bank_service.py`.

Target Hermes dashboard route:
- `/hindsight` if multiple plugin tabs are supported.
- Otherwise `/mission-control/hindsight` internal route/section.

Target API path:
- `GET /api/plugins/mission-control/hindsight/stats?source=all|pc|pi`
- `GET /api/plugins/mission-control/hindsight/health`
- `GET /api/plugins/mission-control/hindsight/facts?q=&context=&source=&from_date=&to_date=&stale_only=&sort=&limit=&offset=`
- `GET /api/plugins/mission-control/hindsight/facts/{fact_id}`
- `PUT /api/plugins/mission-control/hindsight/facts/{fact_id}`
- `DELETE /api/plugins/mission-control/hindsight/facts/{fact_id}?soft_delete=true|false`
- `POST /api/plugins/mission-control/hindsight/facts/bulk-delete`
- `GET /api/plugins/mission-control/hindsight/search?q=...`
- `GET /api/plugins/mission-control/hindsight/stale?source=all|pc|pi`

Auth model:
- All browser routes require upstream dashboard session token.
- Reads are sensitive enough to keep authenticated because memory facts may contain personal data.
- Writes require the same dashboard session token; no separate admin role exists in upstream yet.

WebSocket needs:
- None for initial port.
- Optional future event: fact mutation broadcast over shared operations stream for multi-tab refresh.

Read operations:
- Bank stats and health.
- Paginated fact listing with search, context, source, date, stale-only, and sort filters.
- Fact detail with audit log.
- Stale fact candidates.

Write operations:
- Update fact content/context through auditable overlay edits.
- Soft delete one fact.
- Hard delete only where existing service permits it.
- Bulk soft delete selected facts.

Acceptance checks:
- Stats card renders for `all`, `pc`, and `pi` source filters.
- Fact table supports pagination, filters, search, and stale-only mode.
- Fact detail modal displays content, entities, stale reasons, document id, timestamp, and audit log.
- Edit fact succeeds and refreshed detail/list reflects the change.
- Delete and bulk-delete require authenticated dashboard requests and show affected ids/audit id.
- Empty bank, Hindsight API unavailable, and service misconfiguration states render as actionable empty/error states.

## Contract: Memory Ingest

Plugin name:
- Prefer `mission-control` section under Hindsight: `Memory Ingest`.
- Split candidate only if service-to-service ingestion needs independent deployment.

Source Mission Control routes/services:
- Backend routes: `app/api/memory_ingest.py`.
- Services: `app/services/memory_ingest_service.py`.
- Frontend currently consumes only `getMemoryIngestHealth()` from `frontend/src/lib/api.ts`; ingest metrics/dead-letter endpoints are backend-only today.

Target Hermes dashboard route:
- `/mission-control/hindsight/ingest` or a Hindsight subpanel.

Target API path:
- Browser/admin observability:
  - `GET /api/plugins/mission-control/memory/ingest/health`
  - `GET /api/plugins/mission-control/memory/ingest/metrics`
  - `GET /api/plugins/mission-control/memory/ingest/dead-letter?limit=50`
- Service-to-service replication, if retained in upstream process:
  - `POST /api/plugins/mission-control/memory/ingest`

Auth model:
- Browser observability endpoints require dashboard session token.
- Replication POST must not use the dashboard session token as a long-lived Pi credential. Keep existing HMAC request auth semantics: `X-Hermes-Timestamp`, `X-Hermes-Nonce`, `X-Hermes-Signature`, allowed source validation, replay protection.
- If mounted in upstream, this POST must be a deliberate auth exception in `web_server.py` or handled before dashboard auth middleware, with tests proving only valid HMAC requests pass.

WebSocket needs:
- None initially.
- Optional later: emit ingest success/dead-letter events into the operations stream.

Read operations:
- Ingest health.
- Metrics: checkpoints, lag, counters.
- Dead-letter events with bounded `limit`.

Write operations:
- Accept replicated memory events from Pi via authenticated POST.
- No browser write action except possible future dead-letter retry; not in current source UI.

Acceptance checks:
- Health, metrics, and dead-letter panel loads in authenticated dashboard.
- Unauthenticated browser requests to metrics/dead-letter return 401.
- Valid HMAC ingest POST still works if endpoint is ported.
- Invalid signature, stale timestamp, replayed nonce, malformed JSON, and invalid event schema are rejected.
- Dead-letter list is bounded and does not leak secrets.

## Contract: Linear Harness

Plugin name:
- `mission-control` section `Linear Harness`; split candidate `mission-linear`.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/sessions.tsx`, relevant non-chat portions of `frontend/src/routes/operations.tsx`.
- Backend routes: `app/api/harness.py`, `app/api/workers.py`, `app/api/websocket.py`.
- Services: `app/services/harness_service.py`, `app/services/websocket_manager.py`.

Target Hermes dashboard route:
- `/linear-harness` if plugin tab supports separate route.
- Otherwise `/mission-control/linear-harness`.

Target API path:
- `GET /api/plugins/mission-control/harness/status`
- `GET /api/plugins/mission-control/harness/sessions`
- `POST /api/plugins/mission-control/harness/{session_id}/retry`
- `POST /api/plugins/mission-control/harness/{session_id}/cancel`
- `GET /api/plugins/mission-control/harness/logs/{session_id}`
- `GET /api/plugins/mission-control/workers`
- WebSocket option A: `WS /api/plugins/mission-control/harness/events?token=...`
- WebSocket option B: shared `WS /api/plugins/mission-control/operations/stream?token=...`

Auth model:
- All HTTP endpoints require upstream dashboard session token.
- Retry/cancel are writes and must be protected by session token, with no public exception.
- WebSocket requires dashboard session token in query string initially; do not reuse Mission Control's long-lived bearer token in the browser.

WebSocket needs:
- Yes, for live operations stream.
- Event payload should preserve current fields used by `operations.tsx`: `type`, `timestamp`, `instance` or `source_instance`, `session_id`, `status`, and payload fields such as `tool`, `action`, `path`, `content`, `args`, `data`.
- Client needs reconnect/backoff, pause/resume, clear, bounded scrollback, filters by error/tool_call/thought/completion.

Read operations:
- Harness/webhook status.
- Active/recent harness sessions.
- Worker process list.
- Session logs by session id.
- Live operations events.

Write operations:
- Retry failed session.
- Cancel running session.
- Optional future: acknowledge/annotate event; not in current source.

Acceptance checks:
- Active Linear harness sessions list with status, issue id/title, source, backend, worktree, summary, and last updated time.
- Non-Hermes workers are distinguishable from upstream Hermes sessions; if not, this panel should shrink to only harness-specific controls.
- Retry/cancel call correct backend and update/refetch state.
- Logs view returns bounded logs for a selected session.
- Operations stream connects, rejects missing/invalid token, reconnects on transient close, and displays event filters.
- Chat facade is not included in this plugin.

## Contract: Digest

Plugin name:
- `mission-control` section `Digest`; split candidate `digest`.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/digest.tsx`.
- Backend routes: `app/api/digest.py`.
- Services/models: `app/services/digest_service.py`, `app/models/digest.py`.

Target Hermes dashboard route:
- `/digest` if separate plugin tab is acceptable.
- Otherwise `/mission-control/digest`.

Target API path:
- `GET /api/plugins/mission-control/digest?instance=all|pc|pi&source=&page=1&page_size=50&days=`
- `GET /api/plugins/mission-control/digest/stats?instance=all|pc|pi`
- `GET /api/plugins/mission-control/digest/{entry_id}`
- `POST /api/plugins/mission-control/digest`

Auth model:
- All endpoints require upstream dashboard session token.
- Manual creation is a write and must remain protected.

WebSocket needs:
- None for initial port; polling/refetch is enough.
- Optional future: creation/ingest events can be published to operations stream.

Read operations:
- Paginated digest entries grouped by day.
- Filter by instance, source type, and days.
- Entry detail by id.
- Stats counts by source and instance.

Write operations:
- Create manual digest entry for testing/manual notes, matching current `POST /api/digest` behavior.

Acceptance checks:
- Digest list/history renders and supports paging and filters.
- Stats render and match list filters where applicable.
- Detail view works for an entry id and returns a clear 404 state for missing entries.
- Manual create succeeds with authenticated request and appears after refetch.
- Empty state renders when no entries match filters.

## Contract: Provider Status

Plugin name:
- `mission-control` section `Provider Status`; split candidate `provider-status`.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/providers.tsx`.
- Backend routes: `app/api/provider_status.py`.
- Services: `app/services/provider_status_service.py`.

Target Hermes dashboard route:
- `/provider-status`, or a plugin slot near upstream Models if the upstream slot system supports it cleanly.

Target API path:
- `GET /api/plugins/mission-control/provider-status?instance=all|pc|pi`

Auth model:
- Require upstream dashboard session token. Provider state can reveal operational configuration and key availability.
- Return only boolean/redacted secret presence. Never return API key values or raw secret env content.

WebSocket needs:
- None initially; poll every 30 seconds as current UI does.

Read operations:
- Provider list with provider id/name, status, status reason, current model, base URL, primary flows, last error, and summary counts.
- Filter by `all|pc|pi`.

Write operations:
- None. Upstream Models/Config pages own provider selection and key management.

Acceptance checks:
- Provider matrix renders active/off-limits/exhausted/misconfigured/unknown states.
- Summary counts render and update for each instance filter.
- Base URLs and flow names render, but keys/secrets are absent or redacted.
- Missing provider configuration renders an empty state, not a crash.
- Unauthenticated API request returns 401.

## Contract: Shared Operations Stream

Plugin name:
- Shared service inside `mission-control`; consumed by Linear Harness and optionally other panels.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/operations.tsx`.
- Backend routes: `app/api/websocket.py`.
- Service: `app/services/websocket_manager.py`.

Target Hermes dashboard route:
- `/mission-control/operations` as a standalone stream viewer.
- Also embedded in `/linear-harness` where session-specific activity matters.

Target API path:
- `WS /api/plugins/mission-control/operations/stream?token=<dashboard-session-token>`
- Optional HTTP diagnostic: `GET /api/plugins/mission-control/operations/status`.

Auth model:
- Query token must match upstream dashboard session token, using constant-time compare where possible.
- If the upstream plugin SDK standardizes WebSocket auth, migrate to that standard and update this contract.

WebSocket needs:
- Required.
- Preserve current reconnect/backoff semantics and bounded scrollback.
- Server should send JSON events and ignore or explicitly handle client control messages.

Read operations:
- Stream events only; optional status read.

Write operations:
- Client may send ping/control messages. No persistent write operation in the first port.

Acceptance checks:
- Missing/invalid token closes with policy violation.
- Valid dashboard token receives events.
- Client can pause/resume buffering, reconnect, clear feed, and filter by event category.
- Malformed event payloads do not crash the UI.

## Contract: Cron Ops exception review

Plugin name:
- No plugin by default. Temporary section name if needed: `Cron Ops`.

Source Mission Control routes/services:
- Frontend: `frontend/src/routes/cron.tsx`.
- Backend routes: `app/api/cron.py`.
- Service: `app/services/cron_service.py`.

Target Hermes dashboard route:
- DELETE/HIDE by default because upstream Hermes dashboard owns Cron.
- If upstream lacks Mission Control-specific controls, add `/mission-control/cron-ops` as a temporary ops-only panel.

Target API path if kept:
- `GET /api/plugins/mission-control/cron?instance=all|pc|pi`
- `POST /api/plugins/mission-control/cron/{job_id}/pause?instance=pc|pi`
- `POST /api/plugins/mission-control/cron/{job_id}/resume?instance=pc|pi`
- `POST /api/plugins/mission-control/cron/{job_id}/run?instance=pc|pi`
- `POST /api/plugins/mission-control/cron/{job_id}/retry?instance=pc|pi`
- `PATCH /api/plugins/mission-control/cron/{job_id}`
- `GET /api/plugins/mission-control/cron/{job_id}/logs?lines=50`

Auth model:
- All endpoints require dashboard session token.
- Writes are potentially destructive/expensive and must never be public.

WebSocket needs:
- None initially.
- Optional: job state changes can emit to operations stream.

Read operations:
- Job list by instance.
- Recent job logs.

Write operations:
- Pause, resume, run now, retry last failure, patch job settings.

Acceptance checks before deciding to keep:
- Document exact upstream Cron gaps this panel fills.
- If no unique gap exists, remove from nav/router and do not port.
- If kept, every write requires session token and returns clear success/error messages.

## Contracts intentionally not ported

### Config

Source:
- `app/api/config.py`, `app/services/config_service.py`.

Disposition:
- DELETE/HIDE. Upstream Hermes dashboard owns `/config` and `/env`.

Acceptance checks:
- Mission Control plugin does not expose duplicate config write APIs.
- Any setting needed by a plugin is read server-side through upstream config helpers or explicit plugin config, not through a second browser config editor.

### Generic Sessions

Source:
- Generic portions of `frontend/src/routes/sessions.tsx`, `app/api/harness.py` session list.

Disposition:
- DELETE/HIDE unless entries are Linear harness/non-Hermes worker sessions that upstream `/sessions` cannot show.

Acceptance checks:
- Upstream `/sessions` covers Hermes session archives.
- `/linear-harness` covers only harness-specific session controls.

### Chat facade

Source:
- `frontend/src/components/chatFoundation.tsx`, `app/api/chat.py`, `app/services/chat_service.py`.

Disposition:
- DELETE. Upstream embedded TUI chat is the replacement.

Reason:
- The service executes `scripts/mission_control_chat_turn.py` relative to Mission Control repo root, and that script was not present in inspected files.

Acceptance checks:
- No plugin route proxies chat to the missing runner.
- If chat is required, use `hermes dashboard --tui` and upstream `/chat` instead.

### Token usage

Source:
- `app/api/tokens.py`, `app/services/token_service.py`.

Disposition:
- MERGE/DELETE pending upstream analytics review.

Acceptance checks:
- If upstream analytics/models already show the required token data, do not port.
- If unique aggregation is identified, create a new contract before implementation.

## Cutover checklist for every ported panel

Before hiding the Mission Control page:
1. Plugin manifest tab or internal section is visible in upstream `hermes dashboard`.
2. Plugin HTTP endpoints are mounted under `/api/plugins/mission-control/...`.
3. Unauthenticated HTTP calls to sensitive endpoints return 401.
4. WebSockets reject missing/invalid tokens and work with the dashboard session token.
5. Existing happy-path and empty/error states are covered.
6. Writes have explicit confirmation/error handling and refresh affected queries.
7. No secrets or raw environment values appear in API responses or DOM.
8. Source Mission Control route is removed/hidden only after the upstream replacement passes the acceptance checks above.
