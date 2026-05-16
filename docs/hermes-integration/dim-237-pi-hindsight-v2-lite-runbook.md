# DIM-237: Pi Hermes `v2-lite` Runbook (Hindsight Buffered)

This guide is for the Raspberry Pi Hermes node when PC Hermes owns the shared Hindsight memory.

This version matches the current hardened desktop setup:
- real Mission Control stays on `127.0.0.1:8767`
- real Hindsight API stays on `127.0.0.1:9177`
- Pi reaches them through dedicated LAN-only proxy ports on the PC

## Goal

- Pi Hermes can read/write shared memory while PC is online.
- If PC is offline, Pi buffers writes durably and replays later.
- Noise is reduced (no full turn mirroring).

## What Changed

1. New Pi memory provider: `hindsight_buffered`
   - Wraps `hindsight` provider.
   - Queues `hindsight_retain` writes to durable outbox.
   - Replays to PC ingest endpoint with ACK/checkpoint protocol.
   - Uses stale fallback cache for `hindsight_recall`/`hindsight_reflect`.
   - Does not sync full turn transcripts (`sync_turn` is disabled in buffered mode).
2. PC ingest API endpoint:
   - `POST /api/memory/ingest`
   - `GET /api/memory/ingest/metrics`
   - `GET /api/memory/ingest/dead-letter`
   - `GET /api/memory/ingest/health`
3. Mission Control ingest backend can now target Hindsight directly (`MEMORY_INGEST_BACKEND=hindsight`).

## Pi Implementation Steps

1. Set memory provider:

```bash
hermes config set memory.provider hindsight_buffered
```

2. Add Pi env vars (`~/.hermes/.env`):

```bash
# Pi -> PC ingest through dedicated LAN proxy (required)
HERMES_OUTBOX_ENDPOINT=http://<PC_LAN_IP>:8768/api/memory/ingest
HERMES_OUTBOX_HMAC_SECRET=<shared_hmac_secret>
HERMES_OUTBOX_PEER_NAME=pi

# Hindsight target on PC through dedicated LAN proxy
HINDSIGHT_API_URL=http://<PC_LAN_IP>:9178
HINDSIGHT_BANK=hermes

# Optional tuning
HERMES_OUTBOX_MAX_BATCH_SIZE=100
HERMES_OUTBOX_MAX_QUEUE_SIZE=10000
```

3. Restart Hermes on Pi.

## PC Prerequisites (Required)

PC Mission Control API env must include:

```bash
MEMORY_INGEST_BACKEND=hindsight
MEMORY_INGEST_HMAC_SECRET=<shared_hmac_secret>
MEMORY_INGEST_ALLOWED_SOURCES=["<PI_IP_OR_TAILSCALE_IP>"]
MEMORY_INGEST_HINDSIGHT_BASE_URL=http://127.0.0.1:9177
MEMORY_INGEST_HINDSIGHT_BANK=hermes
```

PC must run:
- Mission Control on `127.0.0.1:8767`
- Hindsight on `127.0.0.1:9177`
- LAN ingest proxy on `8768`
- LAN Hindsight proxy on `9178`

## Verification

1. Check PC ingest health:

```bash
curl -H "Authorization: Bearer <MISSION_CONTROL_BEARER_TOKEN>" \
  http://<PC_LAN_IP>:8768/api/memory/ingest/health
```

2. On Pi, trigger one retain (through normal Hermes usage or memory tool).

3. Check metrics on PC:

```bash
curl -H "Authorization: Bearer <MISSION_CONTROL_BEARER_TOKEN>" \
  http://<PC_IP_OR_TAILSCALE_IP>:8767/api/memory/ingest/metrics
```

Expected:
- checkpoint for `source_peer=pi` increases,
- lag returns toward `0`,
- `dead_letters` stays `0`.

## Notes

- Same WiFi: use LAN IPs only.
- This runbook assumes the PC exposes Pi access through dedicated LAN proxy ports,
  not by rebinding the real Mission Control or Hindsight services to `0.0.0.0`.
- Keep `HERMES_OUTBOX_HMAC_SECRET` (Pi) and `MEMORY_INGEST_HMAC_SECRET` (PC) identical.
