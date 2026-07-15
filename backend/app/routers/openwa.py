"""OpenWA router — session connect (QR), status, and disconnect.

The gateway assigns a UUID per session; we work against a stable session NAME
(settings.openwa_session_name) so the connect flow is idempotent and survives a
recreated session. The resolved UUID is cached via openwa_session so the sender
and every uvicorn worker target the live session.
"""
import logging
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import settings
from app.routers.auth import verify_token
from fastapi import Depends
from app.services.openwa_session import get_active_session_id, set_active_session_id

logger = logging.getLogger("openwa")
router = APIRouter(prefix="/api/openwa", tags=["openwa"])

_headers = lambda: {
    "X-API-Key": settings.openwa_api_key,
    "Content-Type": "application/json",
}


def _base() -> str:
    return settings.openwa_base_url


def _get_session(session_id: str):
    """Fetch a session by UUID. Returns the gateway JSON dict or None."""
    if not session_id:
        return None
    try:
        resp = httpx.get(f"{_base()}/sessions/{session_id}", headers=_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning("Session fetch failed: %s", e)
    return None


def _find_by_name(name: str):
    """Find a session whose name matches. Returns its dict or None."""
    try:
        resp = httpx.get(f"{_base()}/sessions", headers=_headers(), timeout=5)
        if resp.status_code == 200:
            for s in resp.json() or []:
                if s.get("name") == name:
                    return s
    except Exception as e:
        logger.warning("Session list failed: %s", e)
    return None


def _resolve_session(create: bool):
    """Return the live session dict, creating it (by name) when create=True.

    Resolution order: cached/active UUID -> by configured name -> create. The
    resolved UUID is persisted so the sender and other workers use it.
    """
    sess = _get_session(get_active_session_id())
    if sess:
        return sess

    name = settings.openwa_session_name
    sess = _find_by_name(name)
    if sess:
        set_active_session_id(sess.get("id"))
        return sess

    if not create:
        return None

    resp = httpx.post(f"{_base()}/sessions", headers=_headers(), json={"name": name}, timeout=10)
    if resp.status_code in (200, 201):
        sess = resp.json()
        set_active_session_id(sess.get("id"))
        return sess
    if resp.status_code == 409:
        # Race: it was created concurrently — fetch the existing one by name.
        sess = _find_by_name(name)
        if sess:
            set_active_session_id(sess.get("id"))
            return sess
    raise HTTPException(502, f"OpenWA session create failed: {resp.text}")


def _register_webhook(session_id: str):
    """Idempotently ensure exactly ONE webhook for our URL is registered.

    /connect can be called repeatedly (the dashboard auto-polls and the user may
    click Connect again). Without this guard every call POSTed a fresh webhook,
    so the gateway accumulated duplicate registrations and fired N deliveries per
    inbound message — the bot replied and re-assigned tasks N times. We list
    existing webhooks, skip creation if our URL already has one, and prune any
    extras that slipped in earlier.
    """
    url = settings.openwa_webhook_url
    try:
        existing = httpx.get(f"{_base()}/sessions/{session_id}/webhooks",
                             headers=_headers(), timeout=10)
        mine = [w for w in (existing.json() or []) if w.get("url") == url] \
            if existing.status_code == 200 else []
    except Exception as e:
        logger.warning("Webhook list failed (will attempt create): %s", e)
        mine = []

    # Prune duplicates — keep the first, delete the rest.
    for dup in mine[1:]:
        try:
            httpx.delete(f"{_base()}/sessions/{session_id}/webhooks/{dup['id']}",
                         headers=_headers(), timeout=10)
            logger.info("Pruned duplicate webhook %s", dup.get("id"))
        except Exception as e:
            logger.warning("Failed to prune webhook %s: %s", dup.get("id"), e)

    if mine:
        # Already registered — nothing to create.
        return

    try:
        payload = {"url": url, "events": ["message.received"]}
        if settings.openwa_webhook_secret:
            payload["secret"] = settings.openwa_webhook_secret
        wh = httpx.post(f"{_base()}/sessions/{session_id}/webhooks",
                        headers=_headers(), json=payload, timeout=10)
        wh.raise_for_status()
        logger.info("Webhook registered for session %s", session_id)
    except Exception as e:
        logger.warning("Webhook registration failed (non-fatal): %s", e)


@router.get("/status")
def openwa_status(_user=Depends(verify_token)):
    """Gateway reachability + live session status (name, phone, push name)."""
    if not settings.openwa_api_key:
        return {"configured": False, "mode": "dev",
                "message": "OpenWA not configured. Set OPENWA_API_KEY."}
    try:
        resp = httpx.get(f"{_base()}/health", headers=_headers(), timeout=5)
        gateway_ok = resp.status_code == 200
    except Exception as e:
        return {"configured": True, "connected": False, "error": str(e)}

    sess = _resolve_session(create=False) if gateway_ok else None
    return {
        "configured": True,
        "connected": gateway_ok,
        "base_url": settings.openwa_base_url,
        "session_id": (sess or {}).get("id"),
        "session_name": (sess or {}).get("name") or settings.openwa_session_name,
        "session_status": (sess or {}).get("status"),
        "phone": (sess or {}).get("phone"),
        "push_name": (sess or {}).get("pushName"),
    }


class ConnectResponse(BaseModel):
    session_id: str
    status: str
    qr_code: str = ""


@router.post("/connect")
def connect(_user=Depends(verify_token)):
    """Idempotently create+start the WhatsApp session and return its status/QR.

    Safe to call repeatedly: an already-started/ready session is left as-is.
    Poll GET /qr until status is 'ready'.
    """
    if not settings.openwa_api_key:
        raise HTTPException(400, "OpenWA not configured. Set OPENWA_API_KEY first.")
    try:
        sess = _resolve_session(create=True)
    except httpx.RequestError as e:
        raise HTTPException(502, f"Cannot reach OpenWA gateway: {e}")

    session_id = (sess or {}).get("id")
    if not session_id:
        raise HTTPException(502, "OpenWA session could not be created or resolved.")
    status = sess.get("status")

    # Start unless it's already running/authenticated. A 400 here means it's
    # already started — harmless.
    if status not in ("ready", "authenticating", "initializing", "qr_ready"):
        try:
            httpx.post(f"{_base()}/sessions/{session_id}/start", headers=_headers(), timeout=10)
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to start session: {e}")

    _register_webhook(session_id)

    qr = _fetch_qr(session_id)
    refreshed = _get_session(session_id) or sess
    return ConnectResponse(session_id=session_id,
                           status=refreshed.get("status") or "initializing",
                           qr_code=qr)


def _fetch_qr(session_id: str) -> str:
    try:
        resp = httpx.get(f"{_base()}/sessions/{session_id}/qr", headers=_headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("qrCode") or resp.json().get("qrCode", "")
    except Exception as e:
        logger.debug("QR fetch failed: %s", e)
    return ""


@router.get("/qr")
def get_qr(_user=Depends(verify_token)):
    """Current QR data-URL + session status. Returns empty qr once authenticated."""
    session_id = get_active_session_id()
    sess = _get_session(session_id) or {}
    status = sess.get("status")
    qr = "" if status == "ready" else _fetch_qr(session_id)
    return {"qr_code": qr, "status": status, "session_id": session_id or None}


@router.post("/disconnect")
def disconnect(_user=Depends(verify_token)):
    """Stop the live session (logs WhatsApp out until the next connect)."""
    session_id = get_active_session_id()
    if not session_id:
        return {"status": "not_configured"}
    try:
        resp = httpx.post(f"{_base()}/sessions/{session_id}/stop", headers=_headers(), timeout=10)
        return {"status": "stopped" if resp.status_code in (200, 201) else "error",
                "session_id": session_id}
    except Exception as e:
        raise HTTPException(502, f"Failed to stop session: {e}")


# --- Backward-compatible aliases (older frontend builds) -------------------
@router.post("/setup-session")
def setup_session(_user=Depends(verify_token)):
    r = connect()
    return {"session_id": r.session_id, "qr_code_url": r.qr_code, "status": r.status}


@router.get("/session-status")
def session_status(_user=Depends(verify_token)):
    session_id = get_active_session_id()
    sess = _get_session(session_id)
    if not session_id:
        return {"status": "not_configured", "session_id": None}
    return {"status": (sess or {}).get("status", "not_found"), "session_id": session_id}
