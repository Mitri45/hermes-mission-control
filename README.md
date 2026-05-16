# Mission Control API

FastAPI backend for Hermes Web View (Mission Control dashboard).

## Features

- **System Health**: CPU, memory, disk, service monitoring
- **Linear Harness**: Webhook status, active sessions, worker management
- **Token Tracking**: Usage stats by model and time period
- **Real-time Updates**: WebSocket operations stream
- **Configuration**: Runtime agent config management
- **Memory**: Agent memory entries and personality
- **Cron Jobs**: Scheduled job management

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Or with Poetry
poetry install
```

## Usage

```bash
# Start the server
python start.py

# With options
python start.py --host 0.0.0.0 --port 8000 --reload
```

### Dashboard Frontend Build

The `/dashboard` web view serves static assets generated from `frontend/`.
Build the frontend before running dashboard tests or serving the dashboard:

```bash
cd frontend
npm ci
npm run build
```

### Production deployment (DIM-213)

Use the dedicated deployment runbook and systemd manager script:

- `docs/DIM-213_DEPLOYMENT.md`
- `docs/DIM-241_PERIMETER_HARDENING.md`
- `scripts/hermes-mission-control`

Security audit helpers:

```bash
./scripts/hermes-mission-control audit
./scripts/hermes-mission-control audit --runtime
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | System health status (`?instance=all|pc|pi`) |
| `/api/status/health` | GET | Health check |
| `/api/harness/status` | GET | Linear harness status |
| `/api/harness/sessions` | GET | Active agent sessions |
| `/api/harness/{id}/retry` | POST | Retry failed session |
| `/api/harness/{id}/cancel` | POST | Cancel running session |
| `/api/harness/logs/{id}` | GET | Get session logs |
| `/api/workers` | GET | Active worker processes |
| `/api/tokens` | GET | Token consumption stats |
| `/api/config` | GET/POST | Agent configuration |
| `/api/memory` | GET | Memory entries |
| `/api/hindsight/bank/stats` | GET | Hindsight bank statistics |
| `/api/hindsight/bank/facts` | GET | List/filter memory facts |
| `/api/hindsight/bank/facts/{id}` | GET/PUT/DELETE | Inspect, edit, delete fact |
| `/api/hindsight/bank/facts/bulk-delete` | POST | Bulk soft-delete facts |
| `/api/hindsight/bank/search` | GET | Full-text search across facts |
| `/api/hindsight/bank/stale` | GET | Stale fact detection candidates |
| `/api/cron` | GET | Cron jobs |
| `/api/cron/{id}/pause` | POST | Pause job |
| `/api/cron/{id}/resume` | POST | Resume job |
| `/api/v1/provider-status` | GET | LLM/API provider visibility (status, flows, models) |
| `/api/chat` | POST | Send command to agent |
| `/api/operations/stream` | WS | Real-time operations stream |

## Authentication

By default, mutating routes require Bearer token (`AUTH_MODE=write`).
For production hardening, set `AUTH_MODE=all` so read APIs require auth too.

Example:

```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8000/api/config
```

## Development

```bash
# Run tests
pytest

# Format code
black app/
ruff check app/

# Type check
mypy app/
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_HOME` | `~/.hermes` | Hermes config directory |
| `BEARER_TOKEN` | `dev-token` | Bearer token for API auth |
| `AUTH_MODE` | `write` | API auth mode (`write` or `all`) |
| `DASHBOARD_AUTH_MODE` | `public` | Dashboard auth mode (`public`, `bearer`, `cloudflare`) |
| `DASHBOARD_SHARED_SECRET` | unset | Optional dashboard origin secret (`X-Hermes-Origin-Secret`) |
| `EXPOSE_DOCS` | `false` | Expose `/docs` in non-development environments |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `MEMORY_INGEST_BACKEND` | `hindsight` | Ingest sink backend (`hindsight` or `honcho`) |
| `MEMORY_INGEST_HINDSIGHT_BASE_URL` | unset | Preferred Hindsight URL override for Mission Control |
| `MEMORY_INGEST_HINDSIGHT_API_KEY` | unset | Preferred Hindsight API key |
| `MEMORY_INGEST_HINDSIGHT_BANK` | `hermes` | Preferred Hindsight bank id |
| `HINDSIGHT_API_URL` / `HINDSIGHT_BASE_URL` | unset | Compatibility aliases for Hindsight base URL |
| `HINDSIGHT_HOST` + `HINDSIGHT_PORT` + `HINDSIGHT_SCHEME` | unset | Compatibility host/port/scheme overrides when full URL is not set |
| `HINDSIGHT_BANK` / `HINDSIGHT_BANK_ID` | `hermes` | Compatibility aliases for bank id |
| `HERMES_LINEAR_DEFAULT_BACKEND` | `claude-code` | Default Linear backend |
| `HERMES_LINEAR_WORKTREE_ROOT` | `/tmp/hermes-linear-workers` | Worktree directory |
| `PI_STATUS_URL` | unset | Full PI status URL, for example `https://hermes.taildde77c.ts.net/api/status` or `http://pi-host:8771/status` |
| `PI_BEARER_TOKEN` | falls back to `BEARER_TOKEN` | Optional bearer token for remote PI status fetches |

### Lightweight Pi Telemetry

If you do not want the full Mission Control API on the Pi, run the minimal status-only server instead:

```bash
source venv/bin/activate
python scripts/hermes-pi-status-server --host 0.0.0.0 --port 8771 --bearer-token "$BEARER_TOKEN"
```

Then point the PC Mission Control instance at it:

```bash
PI_STATUS_URL=http://<pi-host-or-tailnet-ip>:8771/status
PI_BEARER_TOKEN=<same token if you set one above>
```

The lightweight server exposes:

- `GET /status`
- `GET /api/status`
- `GET /health`
