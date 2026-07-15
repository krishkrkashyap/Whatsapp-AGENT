"""Short per-employee conversation memory in Redis.

Stores the last few turns so elliptical follow-ups ("assign it to him too",
"make it high priority") can be resolved. Best-effort: any Redis failure
degrades to stateless behavior.
"""
import json
import logging
from app.config import settings

logger = logging.getLogger("chat_memory")

_KEY = "chat:hist:{}"
_MAX = 12          # ~6 turns (user+bot)
_TTL = 1800        # 30 minutes


def _redis():
    import redis
    return redis.from_url(settings.redis_url, socket_timeout=3, decode_responses=True)


def append(employee_id: str, role: str, text: str) -> None:
    if not text:
        return
    try:
        r = _redis()
        key = _KEY.format(employee_id)
        r.rpush(key, json.dumps({"role": role, "text": text[:1000]}))
        r.ltrim(key, -_MAX, -1)
        r.expire(key, _TTL)
    except Exception as e:
        logger.warning("chat_memory append failed for %s: %s", employee_id, e)


def recent(employee_id: str, limit: int = 6) -> list:
    try:
        r = _redis()
        raw = r.lrange(_KEY.format(employee_id), -limit, -1)
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except (ValueError, TypeError):
                pass
        return out
    except Exception as e:
        logger.warning("chat_memory recent failed for %s: %s", employee_id, e)
        return []


def format_for_prompt(employee_id: str, limit: int = _MAX) -> str:
    # Inject the full stored window (last 6 turns = 12 entries), not just 3 turns.
    turns = recent(employee_id, limit)
    if not turns:
        return ""
    lines = []
    for t in turns:
        who = "User" if t.get("role") == "user" else "Bot"
        lines.append(f"{who}: {t.get('text', '')}")
    return "\n".join(lines)
