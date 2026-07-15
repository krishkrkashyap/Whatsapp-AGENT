# Deployment Guide — OpenWA Gateway

Replaces Twilio with OpenWA (self-hosted WhatsApp API gateway). Zero per-message costs.

## Architecture

```
Employee WhatsApp → OpenWA Gateway (whatsapp-web.js) → Bot Webhook → FastAPI → OpenWA API → Employee WhatsApp
```

## Prerequisites

- Docker + Docker Compose (with BuildKit enabled)
- A spare WhatsApp number for the bot (scan QR code once)
- 2GB+ RAM for Puppeteer/Chromium

## 1. Environment

Copy and fill `.env` in `wa-bot/main/`:

```env
DATABASE_URL=postgresql+psycopg2://wabot:wabot_secure_password@db:5432/wabot
REDIS_URL=redis://redis:6379/0
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<change-me>
SECRET_KEY=<generate-32-char-random>

# OpenWA — leave blank, will be filled after first deploy
OPENWA_BASE_URL=http://openwa:2785/api
OPENWA_API_KEY=
OPENWA_SESSION_ID=
```

## 2. Deploy Stack

```bash
cd wa-bot/main
docker compose up -d --build
```

First build takes 3-5 minutes (installs Chromium for Puppeteer). Subsequent starts are ~10s.

Verify all services are up:

```bash
docker compose ps
```

All 5 services should show `Up`:
- `wabot-db` — PostgreSQL + pgvector
- `wabot-redis` — Redis cache
- `wabot-openwa` — OpenWA gateway
- `wabot-backend` — FastAPI bot
- `wabot-frontend` — React dashboard

## 3. Get OpenWA API Key

OpenWA auto-generates a master API key on first start. Retrieve it:

```bash
docker logs wabot-openwa 2>&1 | findstr "API Key"
```

If not visible in logs, check the generated config file:

```bash
docker exec wabot-openwa cat /app/data/.env.generated
```

Copy the key and set it in your `.env`:

```env
OPENWA_API_KEY=<the-key-from-logs>
```

Then restart the backend:

```bash
docker compose restart backend
```

## 4. Create WhatsApp Session

The bot needs a WhatsApp session authenticated via QR code.

### Option A: Via API (recommended)

```bash
curl -X POST http://localhost:8000/api/openwa/setup-session
```

Response:

```json
{
  "session_id": "uuid-here",
  "qr_code_url": "data:image/png;base64,...",
  "status": "scan_qr"
}
```

Open the QR code data URL in a browser, or decode it:

```bash
# Save QR to file
curl -s -X POST http://localhost:8000/api/openwa/setup-session | python -c "import sys,json; d=json.load(sys.stdin); open('qr.png','wb').write(__import__('base64').b64decode(d['qr_code_url'].split(',')[1]))"
```

Open `qr.png` and scan with your WhatsApp **Settings → Linked Devices**.

### Option B: Via OpenWA Dashboard

```bash
# OpenWA dashboard
open http://localhost:2886
```

Create a session named `wabot`, start it, and scan the QR code.

### Set Session ID

After scanning and the session shows `READY` status:

```bash
# Get session ID
curl http://localhost:8000/api/openwa/session-status
```

Or list sessions directly:

```bash
curl -H "X-API-Key: $OPENWA_API_KEY" http://localhost:2785/api/sessions
```

Copy the session ID into `.env`:

```env
OPENWA_SESSION_ID=<session-uuid>
```

Then restart:

```bash
docker compose restart backend
```

## 5. Verify

```bash
# OpenWA gateway health
curl http://localhost:2785/api/health

# Bot health
curl http://localhost:8000/health

# OpenWA connection status
curl http://localhost:8000/api/openwa/status
```

Expected status response:

```json
{
  "configured": true,
  "connected": true,
  "session_id": "uuid",
  "session_status": "ready"
}
```

## 6. Send a Test Message

```bash
curl -X POST http://localhost:8000/api/twilio/test \
  -H "Content-Type: application/json" \
  -d '{"to_number": "+919876543210", "message": "Hello from OpenWA bot!"}'
```

If you get a 404, the old Twilio route is gone — call the bot's webhook directly:

```bash
# Simulate an incoming message from an employee
curl -X POST http://localhost:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"event": "message.received", "data": {"from": "919876543210@c.us", "body": "help"}}'
```

## 7. Dashboard

Open `http://localhost:80` and log in with `admin` / your password.

The dashboard now shows:
- **WhatsApp Gateway** status (OpenWA ● Live / DEV Mode / ● Disconnected)
- **Session Status** (ready / disconnected / qr_ready)
- Session ID (truncated)

## Session Persistence

OpenWA saves authentication state to `openwa_data` Docker volume. The session survives container restarts. You only scan the QR code once.

If the session disconnects, OpenWA auto-reconnects with exponential backoff (up to 5 attempts).

To force re-authentication:

```bash
docker compose restart openwa
# Then recreate the session
curl -X POST http://localhost:8000/api/openwa/setup-session
```

## Troubleshooting

### OpenWA container exits immediately

Check logs:

```bash
docker compose logs openwa
```

Common cause: insufficient memory for Chromium. On low-RAM servers, add to `PUPPETEER_ARGS`:

```yaml
PUPPETEER_ARGS: --no-sandbox,--disable-setuid-sandbox,--disable-dev-shm-usage,--disable-gpu,--single-process
```

### QR code won't scan

- The WhatsApp number used to scan must not be the same as any employee number in the system
- Use a dedicated bot number
- On first scan, WhatsApp may show "linking" status for 10-30 seconds

### Webhook not receiving messages

Check OpenWA registered webhooks:

```bash
curl -H "X-API-Key: $OPENWA_API_KEY" http://localhost:2785/api/webhooks
```

Verify the webhook URL points to `http://backend:8000/webhook/whatsapp`. If missing, configure manually:

```bash
curl -X POST -H "X-API-Key: $OPENWA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://backend:8000/webhook/whatsapp", "events": ["message.received"]}' \
  http://localhost:2785/api/sessions/$OPENWA_SESSION_ID/webhooks
```

### "Not configured" in dashboard

Check `.env` has all three `OPENWA_*` vars set and backend was restarted after changes.

## Port Reference

| Service | Port | Purpose |
|---------|------|---------|
| Bot API | 8000 | FastAPI endpoints |
| Bot Frontend | 80 | React dashboard |
| OpenWA API | 2785 | WhatsApp gateway REST API |
| OpenWA Dashboard | 2886 | OpenWA web UI |
| PostgreSQL | 5432 | Database + pgvector |
| Redis | 6379 | Cache / queue |
