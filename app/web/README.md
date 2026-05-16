# Hermes Web View - Dashboard

**Ticket:** DIM-234  
**Description:** Main Dashboard screen for Hermes Mission Control

## Overview

DIM-234 now ships the dashboard as a React + TypeScript app built by Vite and served by FastAPI static files.

Core stack used for current requirements:
- React + TypeScript
- TanStack Router (app shell + routes)
- TanStack Query (API polling/fetch layer)
- TanStack Table (cron grid foundation)
- TanStack Form (memory controls foundation)
- Vercel AI SDK (`ai/react`) chat transport foundation

## Architecture

- FastAPI route `/dashboard` (and `/dashboard/*`) serves `templates/index.html`.
- The template is a minimal host page (`<div id="root"></div>`) loading built assets:
  - `/static/css/dashboard.css`
  - `/static/js/dashboard.js`
- Vite builds from `mission-control-api/frontend` into `app/web/static`.

## Current Scope (DIM-234)

- Main dashboard screen (primary route)
- Global app shell with:
  - Header + instance switcher
  - Status strip
  - Sidebar navigation
- Summary cards:
  - System status
  - Cron status
  - Daily digest summary seed
  - Active sessions summary
- Route foundations for:
  - Cron (`DIM-231`)
  - Daily Digest (`DIM-232`)
  - Provider Visibility (`DIM-235`)
  - Sessions (`DIM-209` chat foundation)
  - Operations Feed (`DIM-209` live stream panel)
  - Memory (`DIM-211` controls foundation)

## DIM-235 Docs Audit (2026-04-09)

Latest docs reviewed before implementation (ticket requirement):

- TanStack Start (latest / Start RC): <https://tanstack.com/start/latest>
- TanStack Router (v1): <https://tanstack.com/router/latest>
- TanStack Query (v5): <https://tanstack.com/query/latest>
- TanStack Table (v8): <https://tanstack.com/table/latest>
- TanStack Form (v1): <https://tanstack.com/form/latest>
- Vercel AI SDK docs (redirects to ai-sdk.dev): <https://sdk.vercel.ai/docs>

## DIM-210 Docs Audit (2026-04-09)

Latest docs reviewed before implementation:

- TanStack Start (Start RC): <https://tanstack.com/start/latest>
- TanStack Router (v1): <https://tanstack.com/router/latest>
- TanStack Query (v5): <https://tanstack.com/query/latest>
- TanStack Table (v8): <https://tanstack.com/table/latest>
- TanStack Form (v1): <https://tanstack.com/form/latest>
- AI SDK (v6 latest): <https://sdk.vercel.ai/docs>

## File Structure

```
mission-control-api/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── routes/
│   │   ├── lib/
│   │   ├── main.tsx
│   │   ├── router.tsx
│   │   └── styles.css
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── app/web/
    ├── __init__.py
    ├── templates/index.html
    └── static/
        ├── css/dashboard.css
        └── js/dashboard.js
```

## Development

From `mission-control-api/frontend`:

```bash
npm install
npm run build
```

Then run backend as usual and open:

```text
http://localhost:8000/dashboard
```

## API Endpoints Used

- `GET /api/status`
- `GET /api/cron`
- `GET /api/harness/sessions`
- `GET /api/harness/status`
- `GET /api/v1/provider-status`
- `WS /api/operations/stream`

## Related Tickets

- `DIM-231`: Cron jobs management screen
- `DIM-232`: Daily digest screen
- `DIM-235`: LLM/API provider visibility panel
- `DIM-209`: Interactive sessions/chat
- `DIM-211`: Memory controls

## Screenshots

Captured from the current DIM-234 implementation using headless browser rendering:

- Dashboard (desktop): `app/web/screenshots/dim-234/dashboard-main-desktop.png`
- Cron (desktop): `app/web/screenshots/dim-234/dashboard-cron-desktop.png`
- Daily Digest (desktop): `app/web/screenshots/dim-234/dashboard-digest-desktop.png`
- Dashboard (mobile): `app/web/screenshots/dim-234/dashboard-main-mobile.png`
- Providers (desktop): `app/web/screenshots/dim-235/providers-main-desktop.png`
- Providers (mobile): `app/web/screenshots/dim-235/providers-main-mobile.png`
- System Health panel (desktop): `app/web/screenshots/dim-210/dashboard-system-health-desktop.png`
- System Health panel (mobile): `app/web/screenshots/dim-210/dashboard-system-health-mobile.png`
