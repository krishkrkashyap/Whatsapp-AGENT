"""FastAPI entry — registers all routers + F-9 scheduler + SEC-3 CORS fix."""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import init_db
from app.config import settings
from app.routers import webhook, employees, tasks, kb, internal, auth, openwa, analytics, escalations, logs, sops
from app.routers import settings as settings_router
from app.routers import department_configs as department_configs_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized. Tables created.")

    # F-9: Start background scheduler
    try:
        from app.services.scheduler import start_scheduler, stop_scheduler
        start_scheduler()
        logger.info("Background scheduler started.")
    except Exception as e:
        logger.warning(f"Scheduler failed to start (non-fatal): {e}")

    yield

    # Shutdown scheduler
    try:
        from app.services.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass

app = FastAPI(
    title="Crusty WhatsApp Agent",
    description="Internal Employee Task Management via WhatsApp — Crusty",
    version="3.0.0",
    lifespan=lifespan,
)

# SEC-3 fix: Restrict CORS in production (configure via env)
allowed_origins = ["http://localhost:5173", "http://localhost:3000", "http://localhost:80"]
if hasattr(settings, 'cors_origins') and settings.cors_origins:
    allowed_origins = settings.cors_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(webhook.router)
app.include_router(employees.router, prefix="/api/employees")
app.include_router(tasks.router, prefix="/api/tasks")
app.include_router(kb.router, prefix="/api/kb")
app.include_router(internal.router)
app.include_router(auth.router)
app.include_router(openwa.router)
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(escalations.router, prefix="/api/escalations", tags=["escalations"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(sops.router)
app.include_router(department_configs_router.router)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Crusty WhatsApp Agent", "version": "3.0.0"}

@app.get("/health/deep")
async def health_deep():
    """FI-6: Deep health check — verifies DB, Redis, and OpenWA connectivity."""
    checks = {"service": "Crusty WhatsApp Agent", "version": "3.0.0"}

    # Database check
    try:
        from app.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"

    # Redis check
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=3)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"

    # OpenWA check
    try:
        import httpx
        if settings.openwa_api_key:
            resp = httpx.get(f"{settings.openwa_base_url}/health", timeout=3)
            checks["openwa"] = "ok" if resp.status_code == 200 else f"status {resp.status_code}"
        else:
            checks["openwa"] = "not_configured"
    except Exception as e:
        checks["openwa"] = f"error: {type(e).__name__}"

    all_ok = all(v == "ok" for k, v in checks.items() if k not in ("service", "version", "openwa"))
    checks["status"] = "ok" if all_ok else "degraded"
    return checks
