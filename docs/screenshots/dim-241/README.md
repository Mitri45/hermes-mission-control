# DIM-241 Screenshot Checklist

Add screenshots/captures used in the PR for DIM-241:

1. `audit --runtime` success output
2. Unauthorized `/dashboard` -> `401`
3. Unauthorized `/static/js/dashboard.js` -> `401`
4. `/api/memory/ingest/health` showing `backend=hindsight` and `ok=true`
5. Firewall rule snapshot showing port `8767` restricted to Pi tailnet source

Suggested naming:

- `audit-runtime-pass.png`
- `dashboard-unauthorized-401.png`
- `static-unauthorized-401.png`
- `ingest-health-hindsight-ok.png`
- `firewall-8767-restricted.png`
