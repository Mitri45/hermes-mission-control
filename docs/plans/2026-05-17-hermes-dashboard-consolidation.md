# Hermes Dashboard + Mission Control Consolidation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task after Linear tickets are created.

Goal: Consolidate overlapping Hermes admin UI into upstream `hermes dashboard`, while preserving Mission Control's ops-only value as dashboard plugins or thin external panels.

Architecture: Treat upstream Hermes dashboard as the shell of record. Port unique Mission Control capabilities into Hermes dashboard plugins with plugin-local FastAPI routers under `/api/plugins/...`. Keep Mission Control standalone only during migration and for anything that cannot safely live inside upstream Hermes yet.

Tech Stack:
- Upstream Hermes repo: `/home/dima/.hermes/hermes-agent`
- Hermes dashboard backend: `hermes_cli/web_server.py`
- Hermes dashboard frontend: `web/src/*`
- Dashboard plugin examples: `plugins/kanban/dashboard/*`, `plugins/hermes-achievements/dashboard/*`
- Mission Control repo: `/home/dima/hermes-mission-control`
- Mission Control backend: `app/api/*`, `app/services/*`
- Mission Control frontend: `frontend/src/*`

Non-goals:
- Do not fork the Hermes dashboard shell unless upstream blocks us.
- Do not duplicate config/env/session/cron/model/skills/profile pages.
- Do not expose the dashboard over LAN/public without explicit auth hardening.
- Do not rewrite Mission Control from scratch. Port the useful pieces.

Current facts:
- Upstream Hermes now has `hermes dashboard` on port 9119.
- Upstream dashboard includes sessions, analytics, models, logs, cron, skills, plugins, profiles, config, env keys, docs, and optional embedded TUI chat.
- Mission Control overlaps on config, sessions, cron, and chat.
- Mission Control remains stronger on Linear harness, Hindsight bank, memory ingest, digest, provider status, and PC/Pi telemetry.
- Linear MCP auth is expired, but direct `LINEAR_API_KEY` GraphQL access works for user Dmitrii Bludov, team `DIM`.

Decision: Use upstream Hermes dashboard as the canonical UI shell. Migrate Mission Control's unique panels into first-class Hermes dashboard plugins. Retire overlapping Mission Control pages once their replacements are verified.

---

## Phase 0: Safety Baseline

### Task 0.1: Snapshot both repos

Objective: Make rollback cheap before touching either codebase.

Files:
- Read-only check: `/home/dima/.hermes/hermes-agent`
- Read-only check: `/home/dima/hermes-mission-control`

Steps:
1. Run `git -C /home/dima/.hermes/hermes-agent status --short --branch`.
2. Run `git -C /home/dima/hermes-mission-control status --short --branch || true`.
3. If Mission Control is not a git repo, create a tarball backup before edits:
   `tar -czf /home/dima/hermes-mission-control-backup-$(date +%Y%m%d-%H%M%S).tgz -C /home/dima hermes-mission-control`.
4. Do not push anything unless explicitly requested.

Verification:
- Backup or clean git state exists.
- Current upstream Hermes commit is recorded in the ticket/notes.

---

## Phase 1: Prove Upstream Dashboard Locally

### Task 1.1: Build and start Hermes dashboard

Objective: Verify upstream dashboard works on this machine before migration.

Files:
- `/home/dima/.hermes/hermes-agent/web/package.json`
- `/home/dima/.hermes/hermes-agent/hermes_cli/web_server.py`

Steps:
1. Run `cd /home/dima/.hermes/hermes-agent && hermes dashboard --no-open --port 9119` in a background process.
2. Open/check `http://127.0.0.1:9119/api/status`.
3. Check that `/sessions`, `/cron`, `/config`, `/env`, `/skills`, `/profiles`, `/plugins`, `/logs`, `/models` load.
4. Run with `--tui` separately and verify `/chat` only if needed.

Verification:
- Dashboard responds on 9119.
- No build/runtime errors in logs.
- Session token protection works for sensitive API routes.

### Task 1.2: Verify plugin loading with existing Kanban plugin

Objective: Confirm the plugin architecture is usable for Mission Control panels.

Files:
- `/home/dima/.hermes/hermes-agent/plugins/kanban/dashboard/manifest.json`
- `/home/dima/.hermes/hermes-agent/plugins/kanban/dashboard/plugin_api.py`
- `/home/dima/.hermes/hermes-agent/web/src/plugins/registry.ts`

Steps:
1. Start dashboard.
2. Confirm Kanban plugin appears if enabled/installed.
3. Hit a plugin API route under `/api/plugins/kanban/...` if available.
4. Confirm plugin routes are protected by dashboard session token.

Verification:
- Plugin tab loads.
- Plugin backend route works.
- WebSocket auth pattern is understood before porting operations streams.

---

## Phase 2: Define Migration Boundaries

### Task 2.1: Mark Mission Control pages as keep/kill/port

Objective: Prevent zombie duplication.

Keep/port:
- Linear Harness -> Hermes plugin `mission-linear`
- Hindsight Bank -> Hermes plugin `hindsight-bank`
- Memory Ingest -> probably part of `hindsight-bank` or separate `memory-ingest`
- Digest -> Hermes plugin `digest`
- Provider Status -> maybe plugin page or slot on Models page
- PC/Pi System Health -> Hermes plugin `fleet-health`
- Operations stream -> shared WebSocket pattern for ops plugins

Kill after replacement:
- Config page
- Sessions page, unless it shows non-Hermes worker sessions
- Cron page, unless it has extra log/retry controls upstream lacks
- Chat facade

Potentially merge:
- Dashboard home can become a plugin landing page aggregating ops cards.

Verification:
- Every Mission Control route has a disposition: keep, port, merge, delete.

### Task 2.2: Create a migration contract document

Objective: Make plugin contracts explicit.

Create:
- `/home/dima/hermes-mission-control/docs/consolidation/plugin-contracts.md`

Content:
- Plugin name
- Source Mission Control routes/services
- Target Hermes dashboard route
- Target API path
- Auth model
- WebSocket needs
- Read/write operations
- Acceptance checks

Verification:
- No panel starts implementation without a contract.

---

## Phase 3: Build Shared Plugin Scaffold

### Task 3.1: Create `mission-control` plugin family scaffold

Objective: Add a predictable structure for custom ops plugins without polluting upstream dashboard core.

Create under Hermes repo:
- `plugins/mission-control/README.md`
- `plugins/mission-control/dashboard/manifest.json`
- `plugins/mission-control/dashboard/plugin_api.py`
- `plugins/mission-control/dashboard/src/index.tsx`
- `plugins/mission-control/dashboard/package.json`

Approach:
- Start as one plugin with multiple internal tabs if plugin SDK makes that easier.
- Split into separate plugins later if bundle/API size gets ugly.
- Use Kanban plugin as template.

Verification:
- New plugin appears in Hermes dashboard.
- New plugin API route returns `{ "status": "ok" }`.
- No core dashboard route changes required.

### Task 3.2: Add shared API client helpers for plugins

Objective: Avoid copy-paste fetch/auth/WebSocket code across panels.

Files:
- `plugins/mission-control/dashboard/src/api.ts`
- `plugins/mission-control/dashboard/src/types.ts`

Steps:
1. Implement `mcFetch(path, options)` using `window.__HERMES_PLUGIN_SDK__.fetchJSON` if available.
2. Implement WebSocket URL helper using dashboard session token pattern.
3. Add types copied/minimized from Mission Control schemas.

Verification:
- One test/demo card can call backend health.

---

## Phase 4: Port High-Value Panels First

Order matters. Port things that upstream does not have.

### Task 4.1: Port PC/Pi Fleet Health

Objective: Replace Mission Control system dashboard with a Hermes plugin panel.

Source:
- `/home/dima/hermes-mission-control/app/api/status.py`
- `/home/dima/hermes-mission-control/app/services/system_monitor.py`
- `/home/dima/hermes-mission-control/frontend/src/routes/dashboard.tsx`

Target:
- Plugin page: `/mission-control` or `/fleet-health`
- API: `/api/plugins/mission-control/status`

Acceptance:
- Shows local PC CPU/memory/disk/service state.
- Shows Pi status through configured `PI_STATUS_URL`.
- Degrades cleanly if Pi is offline.

### Task 4.2: Port Hindsight Bank Manager

Objective: Move memory-bank CRUD/search/stale review into Hermes dashboard.

Source:
- `/home/dima/hermes-mission-control/app/api/hindsight_bank.py`
- `/home/dima/hermes-mission-control/app/services/hindsight_bank_service.py`
- `/home/dima/hermes-mission-control/frontend/src/routes/memory.tsx`

Target:
- Plugin page: `/hindsight`
- API: `/api/plugins/mission-control/hindsight/*`

Acceptance:
- Bank stats visible.
- Facts searchable.
- Fact detail view works.
- Edit/delete/bulk delete require dashboard session auth.
- Stale fact candidates render.

### Task 4.3: Port Linear Harness

Objective: Preserve worker/session operations currently missing upstream.

Source:
- `/home/dima/hermes-mission-control/app/api/harness.py`
- `/home/dima/hermes-mission-control/app/services/harness_service.py`
- `/home/dima/hermes-mission-control/frontend/src/routes/sessions.tsx`
- `/home/dima/hermes-mission-control/frontend/src/routes/operations.tsx`

Target:
- Plugin page: `/linear-harness`
- API: `/api/plugins/mission-control/harness/*`
- WebSocket: `/api/plugins/mission-control/harness/events`

Acceptance:
- Active sessions listed.
- Retry/cancel works.
- Logs view works.
- Operations stream shows live events.

### Task 4.4: Port Provider Status

Objective: Keep visibility into Kimi/MiniMax/custom provider health without duplicating upstream model settings.

Source:
- `/home/dima/hermes-mission-control/app/api/provider_status.py`
- `/home/dima/hermes-mission-control/app/services/provider_status_service.py`
- `/home/dima/hermes-mission-control/frontend/src/routes/providers.tsx`

Target options:
- Standalone plugin page `/provider-status`, or
- Dashboard plugin slot near upstream Models page if slot system supports this cleanly.

Acceptance:
- Shows active primary/fallback providers.
- Shows API key presence only as boolean/redacted state.
- Shows auth/model flow status without leaking secrets.

### Task 4.5: Port Digest

Objective: Preserve digest history/generation if still used.

Source:
- `/home/dima/hermes-mission-control/app/api/digest.py`
- `/home/dima/hermes-mission-control/app/services/digest_service.py`
- `/home/dima/hermes-mission-control/frontend/src/routes/digest.tsx`

Target:
- Plugin page: `/digest`
- API: `/api/plugins/mission-control/digest/*`

Acceptance:
- List/history works.
- Stats work.
- Manual digest generation works.

---

## Phase 5: Retire Overlap

### Task 5.1: Remove or hide overlapping Mission Control pages

Objective: Stop maintaining duplicate UI.

Files:
- `/home/dima/hermes-mission-control/frontend/src/router.tsx`
- `/home/dima/hermes-mission-control/frontend/src/components/shell.tsx`

Actions:
- Hide/remove Config route.
- Hide/remove generic Sessions route after Linear harness has its own page.
- Hide/remove Cron route unless extra controls remain valuable.
- Remove Chat route/facade unless upstream embedded TUI fails.

Verification:
- Mission Control reduced to legacy/deprecated ops-only mode or retired entirely.

### Task 5.2: Fix or delete broken Mission Control chat facade

Objective: Avoid dead code.

Current issue:
- `app/services/chat_service.py` expects `/home/dima/scripts/mission_control_chat_turn.py`, which was not found.

Decision:
- Prefer delete/deprecate if upstream `hermes dashboard --tui` works.
- If kept, fix `REPO_ROOT` and script path with tests.

Verification:
- No broken `/api/chat` route remains exposed.

---

## Phase 6: Deployment and Cutover

### Task 6.1: Pick canonical local dashboard command

Recommendation:
- `hermes dashboard --tui --port 9119`

Acceptance:
- One command starts the real UI shell.
- Optional service script/systemd user unit added only after manual verification.

### Task 6.2: Cloudflare/LAN exposure decision

Objective: Avoid accidental LAN/public exposure of secrets.

Default:
- Keep Hermes dashboard on localhost only.

If remote access is needed:
- Use SSH tunnel or Cloudflare Access with strong origin controls.
- Do not use `--insecure` casually.
- If `--host 0.0.0.0` is required, document token exposure model and network controls.

Acceptance:
- No public unauthenticated dashboard.

### Task 6.3: Archive or freeze Mission Control standalone service

Objective: End duplicate maintenance.

Options:
1. Archive repo after all panels are plugins.
2. Keep only lightweight Pi status server if useful.
3. Keep standalone service for remote ops but remove duplicate pages.

Acceptance:
- README states canonical UI is Hermes dashboard.
- Old service status is explicit: archived, legacy, or Pi-only.

---

## Linear Ticket Breakdown

Create these under team `DIM` after approval:

1. `Consolidation: verify upstream Hermes dashboard baseline`
   - Phase 1 tasks.
   - Priority: High.

2. `Consolidation: write Mission Control plugin contracts`
   - Phase 2 tasks.
   - Priority: High.

3. `Consolidation: scaffold Mission Control dashboard plugin`
   - Phase 3 tasks.
   - Priority: High.

4. `Consolidation: port PC/Pi fleet health panel`
   - Task 4.1.
   - Priority: Medium.

5. `Consolidation: port Hindsight bank manager`
   - Task 4.2.
   - Priority: High.

6. `Consolidation: port Linear harness panel`
   - Task 4.3.
   - Priority: High.

7. `Consolidation: port provider status panel`
   - Task 4.4.
   - Priority: Medium.

8. `Consolidation: port digest panel`
   - Task 4.5.
   - Priority: Low/Medium depending on usage.

9. `Consolidation: retire overlapping Mission Control pages`
   - Phase 5.
   - Priority: Medium.

10. `Consolidation: define dashboard deployment/cutover`
    - Phase 6.
    - Priority: Medium.

Suggested project name:
- `Hermes Dashboard Consolidation`

Definition of done:
- Upstream Hermes dashboard is the only UI for core Hermes admin.
- Mission Control unique ops panels are available as Hermes dashboard plugins.
- Mission Control standalone service is archived, frozen, or reduced to Pi/status-only.
- No duplicate config/session/cron/chat UI remains in active use.
