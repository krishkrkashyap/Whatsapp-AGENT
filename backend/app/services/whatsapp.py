"""WhatsApp service — uses OpenWA gateway instead of Twilio."""
import logging
import httpx
from app.config import settings
from app.services.openwa_session import get_active_session_id

logger = logging.getLogger("whatsapp")

# Reverse mapping: phone JID (919876543210@c.us) → raw chat ID (87973831901323@lid)
# Populated by webhook LID resolver so send_whatsapp can fallback to @lid format.
_lid_reverse_cache = {}


def get_lid_reverse_cache():
    return _lid_reverse_cache


def set_lid_mapping(phone_jid: str, raw_chat_id: str):
    if raw_chat_id and "@lid" in raw_chat_id:
        _lid_reverse_cache[phone_jid] = raw_chat_id


def _get_headers():
    return {
        "X-API-Key": settings.openwa_api_key,
        "Content-Type": "application/json",
    }


def _to_chat_id(phone_number: str) -> str:
    """Convert +1234567890 to 1234567890@c.us (OpenWA format)."""
    return phone_number.lstrip("+") + "@c.us"


def _from_chat_id(chat_id: str) -> str:
    """Convert 1234567890@c.us to +1234567890 (internal format)."""
    raw = chat_id.split("@")[0]
    return f"+{raw}" if not raw.startswith("+") else raw


def _send_via_openwa(chat_id: str, body: str) -> str:
    """Low-level send to OpenWA with a given chatId. Returns response id or raises."""
    resp = httpx.post(
        f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/messages/send-text",
        headers=_get_headers(),
        json={"chatId": chat_id, "text": body},
        timeout=15,
    )
    resp.raise_for_status()
    # OpenWA wraps responses as {success, data, meta} and the send DTO returns
    # {messageId, timestamp} — not {id}. Read messageId (fall back to id).
    data = resp.json().get("data", {})
    return data.get("messageId") or data.get("id", "unknown")


def _lookup_lid_chat_id(phone_jid: str) -> str | None:
    """Find the raw @lid chat id for a phone JID so we can retry a failed send.

    Checks the in-memory reverse cache first, then the persistent LidMapping
    table. The DB fallback is important under multiple uvicorn workers, where
    the worker that received the inbound message (and populated the in-memory
    cache) may not be the one sending the reply.
    """
    cached = _lid_reverse_cache.get(phone_jid)
    if cached:
        return cached
    try:
        from app.database import SessionLocal
        from app.models.lid_mapping import LidMapping
        with SessionLocal() as session:
            row = session.query(LidMapping).filter(LidMapping.phone_jid == phone_jid).first()
            if row:
                lid_chat_id = f"{row.lid_prefix}@lid"
                _lid_reverse_cache[phone_jid] = lid_chat_id
                return lid_chat_id
    except Exception as e:
        logger.warning("LID reverse DB lookup failed for %s: %s", phone_jid, e)
    return None


def send_whatsapp(to_number: str, body: str) -> str:
    """Send WhatsApp message via OpenWA gateway.
    Falls back to raw LID chat ID if phone JID format fails.
    """
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] WhatsApp -> {to_number}: {body[:100]}")
        return "dev-mode-sid"

    phone_jid = _to_chat_id(to_number)
    # Try phone JID format first
    try:
        return _send_via_openwa(phone_jid, body)
    except Exception as e:
        lid_chat_id = _lookup_lid_chat_id(phone_jid)
        if lid_chat_id:
            logger.info("Phone JID send failed (%s), trying LID fallback %s", e, lid_chat_id)
            try:
                return _send_via_openwa(lid_chat_id, body)
            except Exception as e2:
                logger.error(f"LID fallback also failed: {e2}")
                return "error"
        # No fallback available
        logger.error(f"OpenWA send error (no LID fallback): {e}")
        return "error"


def send_whatsapp_with_media(to_number: str, body: str, media_url: str) -> str:
    """Send WhatsApp message with an image/document via OpenWA."""
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] WhatsApp+media -> {to_number}: {body[:60]} ({media_url})")
        return "dev-mode-sid"
    try:
        resp = httpx.post(
            f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/messages/send-image",
            headers=_get_headers(),
            # OpenWA's SendMediaMessageDto expects `url` (or `base64`), not `media`.
            json={"chatId": _to_chat_id(to_number), "caption": body, "url": media_url},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return data.get("messageId") or data.get("id", "unknown")
    except Exception as e:
        logger.error(f"OpenWA media send error: {e}")
        return "error"


def send_whatsapp_media_base64(to_number: str, caption: str, media_base64: str,
                               mimetype: str = "image/jpeg") -> str:
    """Send an image to WhatsApp from an in-memory base64 payload (used to
    forward collected checklist photos). OpenWA's send-image accepts `base64`."""
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] WhatsApp+b64 -> {to_number}: {caption[:60]}")
        return "dev-mode-sid"
    if not media_base64:
        # Nothing to send as an image — fall back to a text note.
        return send_whatsapp(to_number, caption)
    try:
        resp = httpx.post(
            f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/messages/send-image",
            headers=_get_headers(),
            json={"chatId": _to_chat_id(to_number), "caption": caption,
                  "base64": media_base64, "mimetype": mimetype},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return data.get("messageId") or data.get("id", "unknown")
    except Exception as e:
        logger.error(f"OpenWA base64 media send error: {e}")
        return "error"


def send_whatsapp_document(to_number: str, filename: str, file_bytes: bytes,
                           mimetype: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           caption: str = "") -> str:
    """Send a document/file (e.g. the report .xlsx) to WhatsApp via OpenWA's
    send-document, base64-encoded from in-memory bytes."""
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] WhatsApp+doc -> {to_number}: {filename}")
        return "dev-mode-sid"
    import base64
    try:
        resp = httpx.post(
            f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/messages/send-document",
            headers=_get_headers(),
            json={"chatId": _to_chat_id(to_number), "caption": caption, "filename": filename,
                  "base64": base64.b64encode(file_bytes).decode(), "mimetype": mimetype},
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", body)  # send-document returns messageId at top level
        return data.get("messageId") or data.get("id", "unknown")
    except Exception as e:
        logger.error(f"OpenWA document send error: {e}")
        return "error"


_MIME_EXT = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/csv": "csv", "text/plain": "txt", "application/zip": "zip",
}

def _default_filename(mimetype: str) -> str:
    ext = _MIME_EXT.get((mimetype or "").split(";")[0].strip(), "bin")
    return f"attachment.{ext}"

def send_whatsapp_document_base64(to_number: str, caption: str, media_base64: str,
                                  mimetype: str = None, filename: str = None) -> str:
    """Send a document to WhatsApp from an in-memory base64 payload (used to
    forward a received Excel/PDF/doc attachment). OpenWA send-document."""
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] WhatsApp+doc(b64) -> {to_number}: {filename or 'file'}")
        return "dev-mode-sid"
    if not media_base64:
        return send_whatsapp(to_number, caption)
    try:
        resp = httpx.post(
            f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/messages/send-document",
            headers=_get_headers(),
            json={"chatId": _to_chat_id(to_number), "caption": caption,
                  "filename": filename or _default_filename(mimetype),
                  "base64": media_base64, "mimetype": mimetype or "application/octet-stream"},
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", body)
        return data.get("messageId") or data.get("id", "unknown")
    except Exception as e:
        logger.error(f"OpenWA document(b64) send error: {e}")
        return "error"

def send_whatsapp_attachment(to_number: str, caption: str, media_base64: str,
                             mimetype: str = None, filename: str = None) -> str:
    """Route a received media payload by type: images go via send-image, and
    everything else (xlsx, pdf, docs) via send-document — so documents are not
    mangled into a broken image message."""
    if (mimetype or "").startswith("image/"):
        return send_whatsapp_media_base64(to_number, caption, media_base64, mimetype or "image/jpeg")
    return send_whatsapp_document_base64(to_number, caption, media_base64, mimetype, filename)


def send_interactive_buttons(to_number: str, body: str, buttons: list) -> str:
    """Send interactive quick-reply buttons. Falls back to text with options."""
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] Interactive buttons -> {to_number}: {body[:60]}")
        return "dev-mode-sid"
    try:
        button_lines = [f"{b['id']}: {b['title']}" for b in buttons[:3]]
        full_body = f"{body}\n\n{chr(10).join(button_lines)}"
        return send_whatsapp(to_number, full_body)
    except Exception as e:
        logger.error(f"OpenWA buttons error: {e}")
        return send_whatsapp(to_number, body)


def send_interactive_list(to_number: str, body: str, button_text: str, sections: list) -> str:
    """Send interactive list message. Falls back to plain text."""
    if not settings.openwa_api_key or not get_active_session_id():
        logger.info(f"[DEV MODE] Interactive list -> {to_number}: {body[:60]}")
        return "dev-mode-sid"
    try:
        items = []
        for s in sections:
            for item in s.get("items", []):
                items.append(f"  - {item.get('title', '')}: {item.get('description', '')}")
        list_text = "\n".join(items[:10])
        full_body = f"{body}\n\n{list_text}"
        return send_whatsapp(to_number, full_body)
    except Exception as e:
        logger.error(f"OpenWA list error: {e}")
        return send_whatsapp(to_number, body)


def send_template_message(to_number: str, template_sid: str, variables: dict = None) -> str:
    """Template messages not applicable via OpenWA. Falls back to plain text."""
    body = f"[Template: {template_sid}]"
    if variables:
        body += f"\n{variables}"
    return send_whatsapp(to_number, body)
