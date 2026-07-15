"""Active OpenWA session-id resolver.

The gateway assigns a UUID when a session is created, but `OPENWA_SESSION_ID`
in the env is a fixed value that goes stale whenever the session is recreated
(GUI reconnect, wiped gateway volume, etc.). To keep the WhatsApp sender and the
status/QR endpoints pointed at the *live* session across all uvicorn workers, we
cache the resolved UUID in Redis and fall back to the env value.

Sends are low-frequency (task notifications), so a small Redis GET per send is
cheap and always reflects the latest connect — no stale per-worker memory cache.
"""
import logging
from app.config import settings

logger = logging.getLogger("openwa_session")

_REDIS_KEY = "openwa:active_session_id"


def _redis():
    try:
        import redis
        return redis.from_url(settings.redis_url, socket_timeout=2)
    except Exception as e:
        logger.debug("Redis unavailable for session-id cache: %s", e)
        return None


def get_active_session_id() -> str:
    """Live session UUID: Redis cache first, then the configured env value."""
    r = _redis()
    if r:
        try:
            v = r.get(_REDIS_KEY)
            if v:
                return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception as e:
            logger.debug("Redis read failed: %s", e)
    return settings.openwa_session_id


def set_active_session_id(sid: str) -> None:
    """Persist the live session UUID so every worker + the sender pick it up."""
    if not sid:
        return
    # Update this worker's runtime config too (cheap, helps if Redis is down).
    try:
        settings.openwa_session_id = sid
    except Exception:
        pass
    r = _redis()
    if r:
        try:
            r.set(_REDIS_KEY, sid)
        except Exception as e:
            logger.warning("Failed to cache active session id: %s", e)
