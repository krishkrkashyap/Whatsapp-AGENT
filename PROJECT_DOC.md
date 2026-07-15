# WhatsApp Agent — Complete Project Documentation

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Features](#3-features)
4. [Installation & Setup](#4-installation--setup)
5. [Twilio Configuration](#5-twilio-configuration)
6. [WhatsApp Chat Examples](#6-whatsapp-chat-examples)
7. [Admin Dashboard Guide](#7-admin-dashboard-guide)
8. [API Reference](#8-api-reference)
9. [Database Schema](#9-database-schema)
10. [Production Deployment](#10-production-deployment)
11. [Environment Variables](#11-environment-variables)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Project Overview

**WhatsApp Agent** is an internal employee task management system for ~500 staff, powered by WhatsApp messaging via the Twilio API. Admins assign tasks via @mentions, employees confirm completion or request help, and the system handles follow-ups, escalation, and knowledge base lookups — all through WhatsApp.

### Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.12+) |
| Database | PostgreSQL 16 + pgvector |
| Cache/Queue | Redis |
| Frontend | React 18 + Vite + Tailwind CSS |
| Messaging | Twilio WhatsApp API |
| NLP | Anthropic Claude / OpenAI (keyword fallback without API key) |
| Deployment | Docker Compose |

### Key Capabilities
- **Task Assignment**: Admins assign tasks via WhatsApp @mentions
- **Multi-language Support**: English, Hindi, Hinglish, Gujarati detection
- **Auto Follow-ups**: Configurable periodic task reminders
- **RAG Knowledge Base**: Employees get instant answers from company docs
- **Escalation Workflows**: Unresolved issues escalate to admins
- **Admin Dashboard**: Full React SPA for monitoring and management

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────┐
│                    Employee Phone                     │
│              (WhatsApp Client)                        │
└──────────────────────┬───────────────────────────────┘
                       │ Twilio WhatsApp API
                       ▼
┌──────────────────────────────────────────────────────┐
│                    Twilio Cloud                       │
│        (Webhook → POST /webhook/whatsapp)            │
└──────────────────────┬───────────────────────────────┘
                       │ HTTPS
                       ▼
┌──────────────────────────────────────────────────────┐
│                   FastAPI Backend                     │
│  ┌─────────┐  ┌─────────┐  ┌────────────┐           │
│  │ Webhook │→│  NLU    │→│ Task Manager│           │
│  │ Router  │  │ Service │  │  Service    │           │
│  └─────────┘  └─────────┘  └──────┬─────┘           │
│                        │           │                 │
│                  ┌─────▼─────┐ ┌───▼──────┐          │
│                  │ Knowledge │ │ Employee  │          │
│                  │   Base    │ │  Service  │          │
│                  └─────┬─────┘ └───┬──────┘          │
│                        │           │                 │
└────────────────────────┼───────────┼─────────────────┘
                         │           │
                         ▼           ▼
┌──────────────────────────────────────────────────────┐
│                   Data Layer                          │
│  ┌─────────────────────┐  ┌──────────────────────┐   │
│  │  PostgreSQL 16      │  │  Redis               │   │
│  │  + pgvector (RAG)   │  │  (Rate limiting)     │   │
│  └─────────────────────┘  └──────────────────────┘   │
└──────────────────────────────────────────────────────┘
                         ▲
                         │ REST API
                         ▼
┌──────────────────────────────────────────────────────┐
│                 React Admin Dashboard                 │
│  Dashboard · Employees · Tasks · Knowledge Base      │
└──────────────────────────────────────────────────────┘
```

### Message Flow

```
Employee sends WhatsApp message
    │
    ▼
Twilio receives → POST to /webhook/whatsapp
    │
    ▼
Backend looks up employee by phone number
    │
    ├── Unknown number → "You're not registered"
    │
    ▼
NLU parses intent (LLM or keyword fallback)
    │
    ├── TASK_ASSIGN    → Assigns task, notifies target
    ├── TASK_DONE      → Marks task complete, notifies admin
    ├── TROUBLE_HELP   → Searches KB → Answer or escalate
    ├── FOLLOW_UP      → Shows all pending tasks
    ├── STATUS_CHECK   → Shows employee's pending tasks
    └── HELP           → Sends command list
    │
    ▼
Twilio sends response back to employee's WhatsApp
```

---

## 3. Features

### 3.1 Task Management
- **Assign tasks** via @mention in WhatsApp messages
- **Automatic priority detection** (high/medium/low from keywords)
- **Due date parsing** from natural language ("by Friday", "by tomorrow")
- **Mark tasks complete** by replying "done", "ho gaya", "kar diya"
- **View pending tasks** via "my tasks", "all tasks", "team pending"

### 3.2 Multi-language NLP
| Language | Detection Method |
|----------|-----------------|
| English | Default fallback |
| Hindi | Hinglish words (hai, nahi, kya, karna, etc.) |
| Hinglish | Hindi words + Latin script characters |
| Gujarati | Gujarati Unicode character detection |

### 3.3 Knowledge Base (RAG)
- **Upload PDF/TXT documents** via admin dashboard
- **Vector embeddings** stored in pgvector
- **Semantic search** against employee questions
- **Past resolutions** stored for future reference
- **Fallback to keyword matching** when no LLM API key

### 3.4 Escalation & Follow-ups
- **Auto-escalation** when KB can't answer a help request
- **Admin notifications** for all escalations
- **Configurable follow-up intervals** (periodic reminders)
- **Overdue task detection** with automated reminders

### 3.5 Admin Dashboard
- **Real-time metrics** (employees, pending tasks, completed)
- **Employee management** (CSV import, search, department filter)
- **Task monitoring** (status filter, priority filter, auto-refresh)
- **Knowledge base management** (upload, search)
- **Twilio status monitoring** (dev vs production mode)
- **JWT authentication** with token persistence

---

## 4. Installation & Setup

### 4.1 Prerequisites
- Python 3.12+ (3.14 supported but may need C-extension wheels)
- Node.js 20+ and npm
- Docker + Docker Compose (for production or PG with pgvector)
- PostgreSQL 16 with pgvector extension (Docker recommended)

### 4.2 Backend Setup

```bash
cd wa-bot/backend

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate        # Windows
source venv/bin/activate       # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp ../../.env.example .env
# Edit .env with your values

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4.3 Frontend Setup

```bash
cd wa-bot/frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Open http://localhost:5173 → Login with `admin` / `admin123`

### 4.4 Database Setup

**Option A: Existing Docker container (dev)**
```bash
# Use existing hrms-db container on port 5433
# Ensure pgvector extension is installed:
docker exec hrms-db psql -U wabot -d wabot -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**Option B: Docker Compose (production)**
```bash
docker-compose up -d db
# Creates fresh PostgreSQL 16 + pgvector on port 5432
```

### 4.5 Import Sample Employees

```bash
curl -X POST http://localhost:8000/api/employees/import \
  -F "file=@sample_employees.csv"
```

The CSV file has these 8 sample employees:

| Name | Department | Role | WhatsApp | Admin |
|------|-----------|------|----------|-------|
| Raj Patel | Engineering | Developer | +919876543210 | No |
| Priya Sharma | Engineering | Lead | +919876543211 | Yes |
| Amit Singh | Support | Engineer | +919876543212 | No |
| Sneha Desai | HR | Manager | +919876543213 | Yes |
| Vikram Mehta | Finance | Analyst | +919876543214 | No |
| Kiran Joshi | Engineering | Senior Developer | +919876543215 | No |
| Pooja Rao | Marketing | Coordinator | +919876543216 | No |
| Arjun Nair | Operations | Supervisor | +919876543217 | No |

---

## 5. Twilio Configuration

### 5.1 Get Credentials

1. **Sign up**: [console.twilio.com](https://console.twilio.com/)
2. **Account SID**: Dashboard → Account Info → Account SID
3. **Auth Token**: Dashboard → Account Info → Auth Token → View
4. **WhatsApp Sandbox Number**: Messaging → Try it out → Send a WhatsApp message

### 5.2 Join Sandbox (Testing Only)

From your WhatsApp, send to the sandbox number:
```
join <your-sandbox-word>
```
Example: `join two-banana`

### 5.3 Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WHATSAPP_NUMBER=+14155238886
```

### 5.4 Set Webhook URL

**Local testing (ngrok):**
```bash
ngrok http 8000
# Output: https://abc123.ngrok.io → http://localhost:8000
```

In Twilio Console → WhatsApp → Sandbox Settings:
- **"When a message comes in"**: `https://abc123.ngrok.io/webhook/whatsapp`

**Production:**
- Set webhook to `https://yourdomain.com/webhook/whatsapp`

### 5.5 Verify Configuration

```bash
curl http://localhost:8000/api/twilio/status
# {"configured": true, "mode": "production", ...}
```

### 5.6 Send Test Message

```bash
curl -X POST http://localhost:8000/api/twilio/test \
  -H "Content-Type: application/json" \
  -d '{"to_number": "+919876543210", "message": "Test from WA Bot!"}'
```

---

## 6. WhatsApp Chat Examples

### 6.1 Admin Assigns Task

```
👤 Priya Sharma (Admin) → Bot:
@Raj fix the login bug high priority

🤖 Bot → Raj Patel (+919876543210):
📋 *New Task Assigned*

From: Priya Sharma
Task: @Raj fix the login bug high priority
Priority: HIGH

Reply 'done' when complete, or describe your issue for help.

🤖 Bot → Priya Sharma (+919876543211):
✅ Task assigned to Raj Patel: "@Raj fix the login bug high priority"
```

### 6.2 Admin Assigns Task with Due Date

```
👤 Sneha Desai (Admin) → Bot:
@Amit configure the new router by Friday high

🤖 Bot → Amit Singh:
📋 *New Task Assigned*

From: Sneha Desai
Task: @Amit configure the new router by Friday high
Priority: HIGH
Due: 19 May 2026

Reply 'done' when complete, or describe your issue for help.
```

### 6.3 Employee Marks Task Complete

```
👤 Raj Patel → Bot:
done

🤖 Bot → Raj Patel:
✅ '@Raj fix the login bug high priority' marked as done! Great work 🎉

🤖 Bot → Priya Sharma:
✅ Raj Patel completed: "@Raj fix the login bug high priority"
```

### 6.4 Employee Checks Own Tasks

```
👤 Raj Patel → Bot:
my tasks

🤖 Bot → Raj Patel:
📋 *Your pending tasks:*

1. Fix database migration [high] (Due: 20 May)
2. Review PR #142 [medium]
3. Update API docs [low] (Due: 25 May)
```

### 6.5 Admin Checks Team Tasks

```
👤 Priya Sharma (Admin) → Bot:
all tasks

🤖 Bot → Priya Sharma:
📋 *All Pending Tasks:*

• Fix database migration → Raj Patel [high]
• Review PR #142 → Raj Patel [medium]
• Configure new router → Amit Singh [high]
• Prepare Q2 report → Vikram Mehta [medium]
• Social media campaign → Pooja Rao [low]
```

### 6.6 Employee Asks for Help (KB Search)

```
👤 Amit Singh → Bot:
How do I reset the printer network settings?

🤖 Bot → Amit Singh:
🔍 *Solution found:*

To reset printer network settings:
1. Go to Menu → Network → Reset
2. Select "Factory Default Network Settings"
3. Confirm and wait for restart
4. Reconfigure WiFi through the printer panel

---
If this didn't help, reply 'escalate' for admin assistance.
```

### 6.7 Employee Asks for Help (Escalation)

```
👤 Amit Singh → Bot:
The server keeps crashing after deployment

🤖 Bot → Amit Singh:
❌ I couldn't find a solution. I'm notifying the admin.
Someone will help you shortly.

🤖 Bot → Priya Sharma (Admin):
🆘 *Escalation:* Amit Singh needs help!
Query: The server keeps crashing after deployment
Ticket #: a1b2c3d4

🤖 Bot → Sneha Desai (Admin):
🆘 *Escalation:* Amit Singh needs help!
Query: The server keeps crashing after deployment
Ticket #: a1b2c3d4
```

### 6.8 Admin Requests Help Command List

```
👤 Priya Sharma (Admin) → Bot:
help

🤖 Bot → Priya Sharma:
🤖 *WhatsApp Agent — Admin Commands*

📝 *Assign task:* @name task description due date priority
  Example: @Raj fix server bug by Friday high priority

✅ *Employee replies done/ho gaya* → auto-marks complete

❓ *Help/Stuck* → bot searches KB, escalates to you

📋 *My team tasks:* 'all tasks', 'team pending', 'sabka status'

🔄 *Follow up:* 'follow up', 'check all pending'

🆘 *Escalations notified to you automatically*
```

### 6.9 Employee Requests Help Command List

```
👤 Raj Patel → Bot:
help

🤖 Bot → Raj Patel:
🤖 *WhatsApp Agent — Employee Commands*

✅ *Done:* 'done', 'ho gaya', 'complete', 'kar diya'

❓ *Help:* 'stuck', 'error', 'samajh nahi aaya', 'help'

📋 *My tasks:* 'my tasks', 'pending', 'kya karna hai'

Reply to task messages with any issue and bot will try to help!
```

### 6.10 Multi-language Support

```
👤 Raj Patel → Bot (Hinglish):
bhai mera kya pending kaam hai?

🤖 Bot → Raj Patel (Hinglish detected):
📋 *Your pending tasks:*

1. Fix database migration [high] (Due: 20 May)
2. Review PR #142 [medium]

---

👤 Raj Patel → Bot (Hinglish completion):
ho gaya sab

🤖 Bot → Raj Patel:
✅ 'Fix database migration' marked as done! Great work 🎉
```

### 6.11 Unregistered Number

```
👤 +919999999999 → Bot:
hello

🤖 Bot → +919999999999:
❌ You're not registered in our system.
Please contact your admin to get registered.
```

---

## 7. Admin Dashboard Guide

### 7.1 Login
- Navigate to http://localhost:5173
- Default credentials: `admin` / `admin123`
- Session persists for 24 hours via JWT in localStorage

### 7.2 Dashboard Page
- **Employee count** — Total registered employees
- **Pending tasks** — Tasks awaiting completion
- **Completed tasks** — Tasks marked done
- **WhatsApp mode** — Shows DEV or PRODUCTION
- **System status** — Backend, PostgreSQL, Redis connection status
- **Quick Start guide** — Onboarding steps

### 7.3 Employees Page
- **Import CSV** — Upload employee CSV file
- **Search** — Filter by name, role, or WhatsApp number
- **Department filter** — Filter by department dropdown
- **Table** — Shows Name, Department, Role, WhatsApp, Admin status

### 7.4 Tasks Page
- **Search** — Filter tasks by title text
- **Status filter** — All / Pending / In Progress / Done
- **Priority filter** — All / High / Medium / Low
- **Auto-refresh** — Updates every 30 seconds
- **Task count** — Shows filtered vs total count

### 7.5 Knowledge Base Page
- **Upload documents** — PDF or TXT files with title
- **Search** — Semantic search against uploaded documents
- **Results** — Shows title, content snippet, similarity score

---

## 8. API Reference

### Authentication

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| POST | `/api/auth/login` | Login and get JWT token | No |
| GET | `/api/auth/me` | Get current user info | Yes (Bearer token) |

**Login Request:**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**Login Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

### WhatsApp / Messaging

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| POST | `/webhook/whatsapp` | Twilio webhook endpoint | No |
| GET | `/api/twilio/status` | Check Twilio configuration | No |
| POST | `/api/twilio/test` | Send test WhatsApp message | No |

**Webhook Payload (from Twilio):**
```
Body=@Raj fix server bug high priority
From=whatsapp:+919876543211
```

**Webhook Response:**
```json
{
  "status": "ok",
  "intent": "TASK_ASSIGN",
  "language": "english"
}
```

### Employees

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| GET | `/api/employees/` | List all employees | No |
| GET | `/api/employees/count` | Employee count | No |
| POST | `/api/employees/import` | Import employees from CSV | No |

### Tasks

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| GET | `/api/tasks/` | List all tasks | No |
| GET | `/api/tasks/count` | Task count | No |
| GET | `/api/tasks/employee/{id}` | Tasks for specific employee | No |

### Knowledge Base

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| POST | `/api/kb/upload` | Upload PDF/TXT document | No |
| POST | `/api/kb/search` | Search KB with query | No |

### Internal (Admin Operations)

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| POST | `/internal/check-due-tasks` | Check and remind overdue tasks | No |
| POST | `/internal/check-periodic-followups` | Check periodic follow-ups | No |
| GET | `/internal/stats` | Get task statistics | No |

### Health

| Method | Path | Description | Auth Required |
|--------|------|-------------|--------------|
| GET | `/health` | System health check | No |

---

## 9. Database Schema

### Tables

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   employees     │    │     tasks       │    │ conversation_logs│
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ id (PK, UUID)   │◄───│ assigned_by_id  │    │ id (PK, UUID)   │
│ name (VARCHAR)  │    │ assigned_to_id  │───►│ employee_id     │
│ department      │    │ title (VARCHAR) │    │ task_id (FK)    │
│ role (VARCHAR)  │    │ description     │    │ message (TEXT)  │
│ whatsapp_number │    │ status (ENUM)   │    │ direction (ENUM)│
│ is_admin (BOOL) │    │ priority (ENUM) │    │ msg_type (ENUM) │
│ is_active (BOOL)│    │ due_date (DT)   │    │ language        │
│ created_at (DT) │    │ assigned_at(DT) │    │ created_at (DT) │
└─────────────────┘    │ follow_up_type  │    └─────────────────┘
                       │ follow_up_hours │
                       │ last_follow_up  │
                       └───────┬─────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
              ┌─────▼──────┐      ┌──────▼──────┐
              │ follow_ups │      │ kb_documents│
              ├────────────┤      ├─────────────┤
              │ id (PK)    │      │ id (PK)     │
              │ task_id(FK)│      │ title       │
              │ type (ENUM)│      │ content     │
              │ next_trig  │      │ embedding   │
              │ int_hours  │      │ (pgvector)  │
              └────────────┘      │ source      │
                                  │ created_at  │
                                  └─────────────┘
```

### Enum Values

| Enum | Values |
|------|--------|
| `TaskStatus` | `pending`, `in_progress`, `done` |
| `Priority` | `low`, `medium`, `high` |
| `FollowUpType` | `none`, `periodic`, `deadline`, `escalation` |
| `Direction` | `inbound`, `outbound` |
| `MessageType` | `assignment`, `reply`, `trouble`, `system`, `follow_up` |
| `EscalationStatus` | `open`, `acknowledged`, `resolved` |

---

## 10. Production Deployment

### 10.1 Using Docker Compose

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with production values

# 2. Start all services
docker-compose up -d --build

# 3. Verify
docker-compose ps
curl http://localhost:8000/health
curl http://localhost:80    # Frontend
```

### 10.2 Services

| Service | Port | Purpose |
|---------|------|---------|
| `db` | 5432 | PostgreSQL 16 + pgvector |
| `redis` | 6379 | Caching & rate limiting |
| `backend` | 8000 | FastAPI API server |
| `frontend` | 80 | Nginx serving React SPA |

### 10.3 Reverse Proxy (HTTPS)

Add nginx/Caddy in front of port 80:

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;

    location / {
        proxy_pass http://localhost:80;
    }

    location /webhook/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
    }
}
```

### 10.4 Environment for Production

```env
# Twilio
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=your_real_token
TWILIO_WHATSAPP_NUMBER=+14155238886

# Database
DATABASE_URL=postgresql+psycopg2://wabot:STRONG_PASSWORD@db:5432/wabot
REDIS_URL=redis://redis:6379/0

# Auth
ADMIN_USERNAME=admin
ADMIN_PASSWORD=VERY_STRONG_PASSWORD_HERE
SECRET_KEY=$(openssl rand -hex 32)

# LLM (optional)
LLM_API_KEY=your_key
LLM_PROVIDER=anthropic
```

### 10.5 Database Migration

```bash
# Run Alembic migrations
docker-compose exec backend alembic upgrade head
```

---

## 11. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TWILIO_ACCOUNT_SID` | No (for dev) | `""` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | No (for dev) | `""` | Twilio Auth Token |
| `TWILIO_WHATSAPP_NUMBER` | No (for dev) | `""` | Twilio WhatsApp sandbox number |
| `LLM_API_KEY` | No | `""` | Anthropic or OpenAI API key |
| `LLM_PROVIDER` | No | `anthropic` | `anthropic` or `openai` |
| `LLM_MODEL` | No | `claude-3-5-haiku-latest` | Model name for NLU |
| `DATABASE_URL` | Yes | `postgresql+psycopg2://wabot:123@localhost:5433/wabot` | SQLAlchemy connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection URL |
| `ADMIN_USERNAME` | Yes | `admin` | Admin dashboard username |
| `ADMIN_PASSWORD` | Yes | `admin123` | Admin dashboard password |
| `SECRET_KEY` | Yes | `change-me...` | JWT signing key (32+ chars) |
| `HOST` | No | `0.0.0.0` | Server bind address |
| `PORT` | No | `8000` | Server port |

---

## 12. Troubleshooting

### Backend won't start
```bash
# Check Python version (3.12+ required)
python --version

# Reinstall dependencies
pip install --upgrade -r requirements.txt

# Test imports
python -c "from app.main import app; print('OK')"
```

### Database connection refused
```bash
# Check container is running
docker ps | grep hrms-db

# Test connection
docker exec hrms-db psql -U wabot -d wabot -c "SELECT 1"

# Verify port
docker port hrms-db
```

### pgvector not available
```bash
# Install pgvector in existing container
docker exec -it hrms-db /bin/bash
apt-get update && apt-get install -y build-essential postgresql-server-dev-16 git
cd /tmp
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector
make && make install
psql -U wabot -d wabot -c "CREATE EXTENSION vector;"
```

### Webhook not receiving messages
```bash
# 1. Check ngrok is running
ngrok http 8000

# 2. Verify webhook URL in Twilio console
#    Must be: https://YOUR_NGROK_URL/webhook/whatsapp

# 3. Test endpoint directly
curl -X POST http://localhost:8000/webhook/whatsapp \
  -d "Body=help&From=whatsapp:+919876543210"
```

### Frontend not connecting to backend
```bash
# Verify vite proxy in vite.config.ts
# Must include: '/api', '/webhook', '/internal', '/health'

# Check backend is accessible
curl http://localhost:8000/health
```

### Auth token expired
- Default expiry: 24 hours
- Change in `app/routers/auth.py`: `timedelta(hours=24)` → desired duration
- User is auto-redirected to login on 401

### Twilio test fails with 400
- Ensure all 3 env vars are set: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER`
- Verify account SID starts with `AC`
- Check sandbox is joined on your phone

---

## Quick Reference Card

### Admin WhatsApp Commands
| Message | Result |
|---------|--------|
| `@Name task description` | Assign task to employee |
| `@Name task by Friday high` | Assign with due date + priority |
| `all tasks` | See all team pending tasks |
| `team pending` | See all team pending tasks |
| `follow up` | Check and remind overdue tasks |
| `help` | Show admin command list |

### Employee WhatsApp Commands
| Message | Result |
|---------|--------|
| `done` / `ho gaya` | Mark latest task complete |
| `my tasks` / `pending` | See your pending tasks |
| `stuck` / `error` / `help` | Get KB answer or escalate |
| `help` | Show employee command list |

### File Structure
```
wa-bot/
├── .env.example                    # Environment template
├── docker-compose.yml              # Production deployment
├── SETUP.md                        # Quick setup guide
├── PROJECT_DOC.md                  # This document
├── sample_employees.csv            # Sample employee data
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── config.py               # Settings + env vars
│   │   ├── database.py             # SQLAlchemy setup
│   │   ├── main.py                 # FastAPI app + routers
│   │   ├── models/                 # SQLAlchemy models
│   │   │   ├── employee.py
│   │   │   ├── task.py
│   │   │   ├── conversation.py
│   │   │   ├── kb_document.py
│   │   │   └── escalation.py
│   │   ├── routers/                # API endpoints
│   │   │   ├── auth.py             # JWT login
│   │   │   ├── twilio.py           # Twilio status/test
│   │   │   ├── webhook.py          # WhatsApp handler
│   │   │   ├── employees.py
│   │   │   ├── tasks.py
│   │   │   ├── kb.py
│   │   │   └── internal.py
│   │   ├── services/               # Business logic
│   │   │   ├── nlu.py              # NLP + keyword parser
│   │   │   ├── whatsapp.py         # Twilio sender
│   │   │   ├── task_manager.py
│   │   │   ├── employee_svc.py
│   │   │   └── knowledge_base.py   # RAG + pgvector
│   │   └── utils/
│   │       └── helpers.py          # Mention/priority/date extractors
│   └── tests/
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx                 # Routes + ProtectedRoute
        ├── api/
        │   └── client.ts           # API client + auth
        ├── components/
        │   ├── Layout.tsx
        │   └── Sidebar.tsx         # Nav + logout
        └── pages/
            ├── Login.tsx           # Auth page
            ├── Dashboard.tsx       # Stats + auto-refresh
            ├── Employees.tsx       # Search + filter + import
            ├── Tasks.tsx           # Status/priority filter + search
            └── KnowledgeBase.tsx   # Upload + search
```
