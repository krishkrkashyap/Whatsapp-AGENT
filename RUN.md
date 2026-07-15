# Run — OpenWA Gateway (WhatsApp Agent)

## Prerequisites

- Docker Desktop (Windows) or Docker Compose (Linux/Mac)
- Git
- A WhatsApp account (for the bot number)
- A phone to scan QR code

## Quick Start

```bash
# 1. Clone and enter
cd openwa-gateway

# 2. Start all services
docker compose up -d

# 3. Wait for services to be healthy (~30s)
docker compose ps
# All 4 containers should show "Up" / "healthy"

# 4. Open Dashboard
#    http://localhost:3000
#    Login: admin / admin123
```

## QR Code — First Time Setup

If no session exists or you need a fresh QR:

### Option A: Via Dashboard (easier)
```bash
# 1. Open: http://localhost:3000
# 2. Check session status top-right — if "disconnected", click "Setup Session"
# 3. A QR code image is generated at:
#    http://localhost:3000/api/openwa/qr-code
#    OR check whatsapp_qr.png in the project folder
# 4. Open WhatsApp on phone → Menu → Linked Devices → Link a Device
# 5. Scan the QR code from the image
```

### Option B: Via API
```bash
# Create a new session
curl -X POST http://localhost:3000/api/openwa/setup-session

# Get QR code URL from response, open in browser
# Scan with phone
```

### Option C: Check session status
```bash
curl http://localhost:3000/api/openwa/session-status
# Returns: {"status":"ready","session_id":"..."}
```

## Useful Commands

### Service management
```bash
# Start all
docker compose up -d

# Stop all (preserves data)
docker compose down

# Stop + delete volumes (fresh start, lose DB + session)
docker compose down -v

# Restart a single service
docker compose restart backend
docker compose restart frontend
```

### Rebuild after code changes
```bash
# Backend (Python/FastAPI) — ~30s
docker compose build backend
docker compose up -d backend

# Frontend (React/nginx) — ~20s
docker compose build frontend
docker compose up -d frontend

# OpenWA Gateway (Node.js) — ~5min (Chromium)
docker compose build openwa
docker compose up -d openwa
```

### View logs
```bash
# Follow all logs
docker compose logs -f

# Specific service
docker compose logs backend -f --tail 50
docker compose logs openwa -f --tail 50
docker compose logs frontend -f --tail 50
```

### Reset and re-authenticate
If the session gets stuck or QR expires:
```bash
# 1. Stop OpenWA
docker compose stop openwa

# 2. Delete session data
docker compose run --rm openwa sh -c "rm -rf /app/data/sessions/*"

# 3. Start OpenWA
docker compose up -d openwa

# 4. Wait for it to be ready (~30s)
# 5. Get new QR from dashboard or API
# 6. Scan with phone
```

If Chrome lock files cause "profile in use" errors (after restart):
```bash
docker compose restart openwa
```
(The compose `command` already cleans lock files on startup.)

## Architecture

```
Phone ←→ WhatsApp Web ←→ OpenWA (whatsapp-web.js)
                              ↓
                         Backend (FastAPI + PostgreSQL)
                              ↓
                      Frontend (React + nginx)
                          ↑  Dashboard
```

- **Phone**: WhatsApp account that scans QR (e.g. 919876543210)
- **OpenWA**: WhatsApp automation gateway (port 2785)
- **Backend**: FastAPI app (port 8000) — webhook receiver, NLU, task management
- **Frontend**: React dashboard (port 3000) — employee/task management
- **DB**: PostgreSQL 16 with pgvector (port 5432)
- **Redis**: Task scheduling, caching (port 6379)

## Connectivity

| Container | Internal URL | External Port |
|-----------|-------------|---------------|
| Frontend  | http://frontend:80 | 3000 |
| Backend   | http://backend:8000 | 8000 |
| OpenWA    | http://openwa:2785/api | 2785 |
| DB        | postgresql://db:5432 | 5432 |
| Redis     | redis://redis:6379 | 6379 |

## Environment Variables

All in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| LLM_API_KEY | Groq/OpenAI key for NLU | — |
| LLM_PROVIDER | LLM provider (groq/openai) | groq |
| LLM_MODEL | Model name | llama-3.3-70b-versatile |
| OPENWA_BASE_URL | OpenWA internal URL | http://openwa:2785/api |
| OPENWA_API_KEY | OpenWA auth key | (auto-generated) |
| OPENWA_SESSION_ID | Active session UUID | (from setup) |
| OPENWA_WEBHOOK_URL | Backend webhook URL | http://172.21.0.5:8000/webhook/whatsapp |
| ADMIN_USERNAME | Dashboard admin | admin |
| ADMIN_PASSWORD | Dashboard password | admin123 |

## Common Issues

### "No LID for user" errors in logs
WhatsApp Web's transition to LID identifiers can cause message send failures. The backend auto-resolves LID from message history — send a message to trigger the resolution. If it persists, the phone needs to have the contact saved or the session may need a fresh QR scan.

### Webhook not receiving messages
```bash
# Check webhook is registered
curl -s http://localhost:2785/api/sessions/<SESSION_ID>/webhooks \
  -H "X-API-Key: $OPENWA_API_KEY"

# Webhook URL must point to backend: http://172.21.0.5:8000/webhook/whatsapp
```
If missing, re-run session setup from the Dashboard.

### QR scan not working
- Make sure phone has stable internet
- Try Option B (delete session data, fresh session)
- Check `whatsapp_qr.png` was regenerated

### "Connection closed" / session keeps disconnecting
- Phone must stay connected to internet
- Docker network must be stable
- Check Chrome lock files (restart OpenWA to auto-clean)

## Testing the Bot

After QR scan and session shows "ready":

```bash
# 1. Send WhatsApp message to the bot number from a registered admin
#    Example: "@Ruchi Coordinate team standup tomorrow 10am"
#    Or: "help"

# 2. Check response in WhatsApp
# 3. Check Dashboard → Tasks for assigned tasks
```

## Port Conflicts

If ports conflict with other services, edit `docker-compose.yml`:
- Backend: change `8000:8000` to `8001:8000`
- Frontend: change `3000:80` to `3001:80`
- OpenWA: change `2785:2785` to `2786:2785`
