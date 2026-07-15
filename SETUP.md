# WhatsApp Agent — Setup & Twilio Webhook Guide

## Quick Start

### 1. Backend (Local Dev)
```bash
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 → Login with `admin` / `admin123`

### 3. Database (Docker)
The existing `hrms-db` container (port 5433) is used for dev with pgvector.

For production, use `docker-compose up -d` (creates new PG container on port 5432).

---

## Twilio Setup for Real WhatsApp Testing

### Step 1: Get Twilio Credentials
1. Sign up at [console.twilio.com](https://console.twilio.com/)
2. Copy **Account SID** and **Auth Token** from dashboard
3. Go to **Messaging → Try it out → Send a WhatsApp message**
4. Follow the sandbox setup to get your sandbox number (e.g., `+14155238886`)

### Step 2: Configure Environment
Copy `.env.example` to `.env` in project root:
```bash
cp .env.example .env
```

Edit `.env`:
```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WHATSAPP_NUMBER=+14155238886
```

### Step 3: Verify Configuration
```bash
curl http://localhost:8000/api/twilio/status
```
Should return: `{"configured": true, "mode": "production"}`

### Step 4: Send Test Message
```bash
curl -X POST http://localhost:8000/api/twilio/test \
  -H "Content-Type: application/json" \
  -d '{"to_number": "+919876543210", "message": "Hello from WA Bot!"}'
```

### Step 5: Set Up Webhook
The webhook endpoint is: `POST /webhook/whatsapp`

**Option A: ngrok (local testing)**
```bash
ngrok http 8000
# Copy the HTTPS URL, append /webhook/whatsapp
# e.g., https://abc123.ngrok.io/webhook/whatsapp
```

In Twilio Console → WhatsApp → Sandbox Settings → "When a message comes in":
- Set to your ngrok URL + `/webhook/whatsapp`

**Option B: Production server**
- Deploy to your server with HTTPS
- Set Twilio webhook URL to `https://yourdomain.com/webhook/whatsapp`

### Step 6: Test End-to-End
1. Join Twilio WhatsApp sandbox (send `join <sandbox-word>` from your phone)
2. Send `help` → Bot replies with commands
3. Admin sends `@Raj fix server bug high priority` → Raj gets task assigned
4. Raj (from his WhatsApp) sends `done` → Task marked complete

---

## Admin Dashboard Auth

Default credentials: `admin` / `admin123`

Change in `.env`:
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=CHANGE_ME_SECURE_PASSWORD
SECRET_KEY=CHANGE_ME_TO_LONG_RANDOM_STRING_32+CHARS
```

---

## Production Deployment

```bash
# Copy .env.example and fill in all values
cp .env.example .env

# Build and start all services
docker-compose up -d --build

# Check logs
docker-compose logs -f backend
```

Services:
- **Backend**: `http://localhost:8000`
- **Frontend**: `http://localhost:80`
- **PostgreSQL**: port 5432
- **Redis**: port 6379

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/auth/login` | Admin login (returns JWT) |
| GET | `/api/auth/me` | Get current user |
| GET | `/api/twilio/status` | Check Twilio config |
| POST | `/api/twilio/test` | Send test WhatsApp message |
| POST | `/webhook/whatsapp` | Twilio webhook |
| GET | `/api/employees/` | List employees |
| POST | `/api/employees/import` | Import CSV |
| GET | `/api/tasks/` | List tasks |
| POST | `/api/kb/upload` | Upload KB document |
| POST | `/api/kb/search` | Search KB |
| POST | `/internal/check-due-tasks` | Check overdue tasks |
| GET | `/internal/stats` | Dashboard stats |
