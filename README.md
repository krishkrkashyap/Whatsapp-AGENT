# Whatsapp-Bot-v2 — Crusty WhatsApp Agent

Internal employee task-management bot over WhatsApp for **Cafe Upper Crust**. Admins assign tasks, staff complete them (text or photo/document proof), SOPs run on schedule, and a React dashboard tracks everything.

## Stack
- **Backend** — FastAPI (Python), PostgreSQL + pgvector, Redis, APScheduler. Multi-LLM NLU (Anthropic / OpenAI / Groq / Gemini) with keyword fallback.
- **Frontend** — React + Vite + Tailwind admin dashboard.
- **WhatsApp gateway** — [OpenWA](https://github.com/rmyndharis/OpenWA) v0.8.17 with the **Baileys** engine (protocol-level, no browser — resilient to WhatsApp Web changes).
- **Orchestration** — Docker Compose (db, redis, openwa, backend, frontend).

## Features
- Task assignment / completion over WhatsApp (English + Hindi/Hinglish).
- **SOPs** — recurring scheduled tasks (daily / hourly / weekly), imported from Excel, per-day missed-rollover, on-leave handling.
- **Attachments** — photo + document (xlsx/pdf) proof, forwarded to the assigner.
- **Context-aware completion** — a plain report ("previous day KOT is 10") completes the matching task.
- **Reports** — date-ranged performance xlsx (KPIs, SOP adherence, WhatsApp adoption, all-tasks), plus a daily auto-send.
- Escalations, knowledge base (RAG), conversation logs, analytics.

## Run
```bash
cp .env.example .env      # fill LLM key, DB password, secret key
docker compose up -d --build
# dashboard: http://127.0.0.1:3000   |   backend: http://127.0.0.1:8000
```

WhatsApp: dashboard → Settings → WhatsApp Connection → scan the QR once.

## Layout
```
backend/          FastAPI app (routers, services, models, scheduler)
frontend/         React admin dashboard
openwa-v0817/     OpenWA v0.8.17 gateway (Baileys engine) build context
docker-compose.yml
```

## Notes
- **Gateway not vendored.** `openwa-v0817/` (the OpenWA v0.8.17 build context referenced by compose) is third-party and git-ignored. Before `docker compose up`, clone [OpenWA](https://github.com/rmyndharis/OpenWA) v0.8.17 into `openwa-v0817/`, or point the `openwa` service `build:` at your own checkout.
- Secrets live in `.env` (git-ignored). Never commit real keys.
- The gateway runs the Baileys engine because WhatsApp's web-client updates break browser-scraping engines; Baileys speaks the protocol directly.
