"""Webhook router — Accepts OpenWA JSON webhooks (was Twilio form-data)."""
import json
import re
import hmac
import hashlib
import logging
import httpx
from datetime import datetime, timezone
from collections import OrderedDict
from fastapi import APIRouter, Request, Depends
from sqlalchemy import select
from app.database import get_db, SessionLocal
from app.config import settings
from app.models.lid_mapping import LidMapping
from app.services.whatsapp import send_whatsapp, send_interactive_buttons, set_lid_mapping
from app.services.openwa_session import get_active_session_id
from app.services.employee_svc import EmployeeService
from app.services.task_manager import TaskManager
from app.services.knowledge_base import KBService
from app.services.nlu import nlu_service
from app.services.assistant_service import answer as assistant_answer
from app.services import chat_memory
from app.utils.helpers import extract_mention, extract_priority, extract_due_date, extract_task_number, extract_requires_attachment, parse_edit_due_date, is_done_command
from app.models.escalation import EscalationTicket, EscalationStatus
from app.models.employee import Employee
from app.models.conversation import Direction, MessageType
from app.models.pending_registration import PendingRegistration, RegistrationStatus
from app.models.task import TaskStatus

logger = logging.getLogger("webhook")
router = APIRouter()

# Translation helper — translates hardcoded strings to user's language via LLM
# BUG-C5 fix: Use LRU cache (max 500 entries) instead of unbounded dict
_t_cache: OrderedDict = OrderedDict()
_T_CACHE_MAX = 500

def _t(text: str, lang: str = "english") -> str:
    """Translate hardcoded response to target language. Cached per string."""
    if lang == "english" or not lang:
        return text
    key = ("_t", text, lang)
    cached = _t_cache.get(key)
    if cached:
        _t_cache.move_to_end(key)
        return cached
    translated = nlu_service.translate(text, lang)
    _t_cache[key] = translated
    while len(_t_cache) > _T_CACHE_MAX:
        _t_cache.popitem(last=False)
    return translated

def _verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Verify OpenWA's HMAC-SHA256 webhook signature (header 'X-OpenWA-Signature').
    Returns True when no secret is configured (verification disabled)."""
    secret = getattr(settings, "openwa_webhook_secret", "")
    if not secret:
        return True
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _is_duplicate_delivery(idempotency_key: str) -> bool:
    """Dedupe retried webhook deliveries via a short-lived Redis marker.
    OpenWA retries on timeout/non-2xx, and our handler can be slow (LLM calls),
    so without this a retry would re-process the same message. Fails OPEN
    (treats as non-duplicate) when Redis is unavailable."""
    if not idempotency_key:
        return False
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=3)
        was_new = r.set(f"webhook:seen:{idempotency_key}", "1", nx=True, ex=600)
        return not bool(was_new)
    except Exception:
        return False


# Workers send one OR MANY proof photos for an attachment-required task, often as
# separate messages before typing 'done'. We accumulate them in a Redis list and
# forward the whole set to the admin when the task is marked done.
_PROOF_KEY = "proofs:{}"
_PROOF_MAX = 30          # safety cap on photos per task
_PROOF_TTL = 900         # 15 minutes


def _add_proof_image(employee_id: str, media_b64: str, media_mime: str, media_name: str = None) -> int:
    """Append a proof attachment (photo OR document); return running count."""
    if not media_b64:
        return 0
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=3)
        key = _PROOF_KEY.format(employee_id)
        r.rpush(key, json.dumps({"b64": media_b64, "mime": media_mime or "image/jpeg", "name": media_name}))
        r.ltrim(key, -_PROOF_MAX, -1)
        r.expire(key, _PROOF_TTL)
        return r.llen(key)
    except Exception as e:
        logger.warning("Failed to add proof attachment for %s: %s", employee_id, e)
        return 0


def _get_proof_images(employee_id: str) -> list:
    """Read all held proof attachments WITHOUT consuming them.
    Returns [(b64, mime, filename)]. Cleared via _clear_proofs on done."""
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=3)
        out = []
        for item in r.lrange(_PROOF_KEY.format(employee_id), 0, -1):
            try:
                d = json.loads(item)
                out.append((d.get("b64"), d.get("mime"), d.get("name")))
            except (ValueError, TypeError):
                pass
        return out
    except Exception as e:
        logger.warning("Failed to read proofs for %s: %s", employee_id, e)
        return []


def _is_image(mime: str) -> bool:
    return (mime or "").startswith("image/")


def _clear_proofs(employee_id: str) -> None:
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_timeout=3)
        r.delete(_PROOF_KEY.format(employee_id))
    except Exception:
        pass


def _is_escalate_command(text: str) -> bool:
    """Detect an explicit escalation request. The bot tells stuck users to type
    'escalate' after an unhelpful answer, so this must be recognized and forced
    through to the admins (the keyword parser otherwise treats it as a generic
    question)."""
    t = (text or "").lower()
    return bool(re.search(r"\bescalat", t)) or "admin ko bolo" in t or "admin ko bhejo" in t


def _leave_command(text: str):
    """Detect self-service leave toggle. Returns 'leave', 'return', or None."""
    t = (text or "").strip().lower()
    if t in ("on leave", "leave", "chutti", "chhutti", "i am on leave", "मैं छुट्टी पर हूँ"):
        return "leave"
    if re.search(r"\bon leave\b", t) or re.search(r"\bchh?utti\b", t):
        return "leave"
    if t in ("back", "resume", "available", "off leave", "back from leave", "wapas", "duty", "on duty"):
        return "return"
    if re.search(r"\b(back from leave|off leave|resume duty)\b", t):
        return "return"
    return None


# In-memory LID → phone JID cache (warmed from DB on first access)
_lid_cache = {}

def _persist_lid_mapping(lid_prefix: str, phone_jid: str):
    """Save resolved LID mapping to DB so it survives restarts."""
    try:
        with SessionLocal() as session:
            existing = session.query(LidMapping).filter(LidMapping.lid_prefix == lid_prefix).first()
            if not existing:
                session.add(LidMapping(lid_prefix=lid_prefix, phone_jid=phone_jid))
                session.commit()
    except Exception as e:
        logger.warning("Failed to persist LID mapping %s->%s: %s", lid_prefix, phone_jid, e)

def _resolve_lid(lid: str) -> str | None:
    """Resolve LID (e.g. '87973831901323@lid') to phone JID (e.g. '919876543210@c.us')
       Order: in-memory cache → DB → OpenWA contacts API → message history.
       Resolved mappings are persisted to DB."""
    if not lid or "@lid" not in lid:
        return None
    lid_prefix = lid.split("@")[0]

    # 1. In-memory cache (fastest)
    cached = _lid_cache.get(lid_prefix)
    if cached:
        return cached

    # 2. DB cache (survives restarts)
    try:
        with SessionLocal() as session:
            row = session.query(LidMapping).filter(LidMapping.lid_prefix == lid_prefix).first()
            if row:
                _lid_cache[lid_prefix] = row.phone_jid
                return row.phone_jid
    except Exception as e:
        logger.warning("LID DB lookup failed: %s", e)

    if not settings.openwa_api_key or not get_active_session_id():
        return None

    # 3. Contacts API: WhatsApp stores a contact entry with `number = LID_prefix`
    #    and `id = phone_JID@c.us` for users with LIDs.
    phone_jid = None
    try:
        resp = httpx.get(
            f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/contacts",
            headers={"X-API-Key": settings.openwa_api_key},
            timeout=15,
        )
        if resp.status_code == 200:
            body = resp.json()
            # Handle nested data format: {data: [...], Count: N} or flat list
            if isinstance(body, dict) and "data" in body:
                contacts_list = body["data"]
            elif isinstance(body, dict) and "contacts" in body:
                contacts_list = body["contacts"]
            elif isinstance(body, list):
                contacts_list = body
            else:
                contacts_list = []
            for contact in contacts_list:
                if isinstance(contact, dict) and contact.get("number") == lid_prefix:
                    phone_jid = contact.get("id", "")
                    if phone_jid and "@c.us" in phone_jid:
                        _lid_cache[lid_prefix] = phone_jid
                        _persist_lid_mapping(lid_prefix, phone_jid)
                        logger.info("Resolved LID %s to phone JID %s via contacts", lid_prefix, phone_jid)
                        return phone_jid
    except Exception as e:
        logger.warning("LID resolution via contacts failed: %s", e)

    # 4. Fallback: scan message history for waMessageId containing LID prefix
    try:
        resp = httpx.get(
            f"{settings.openwa_base_url}/sessions/{get_active_session_id()}/messages",
            headers={"X-API-Key": settings.openwa_api_key},
            params={"limit": 100},
            timeout=10,
        )
        if resp.status_code == 200:
            for m in resp.json().get("messages", []):
                wid = m.get("waMessageId") or ""
                if lid_prefix in wid:
                    phone_jid = m.get("chatId") or ""
                    if phone_jid and "@c.us" in phone_jid:
                        _lid_cache[lid_prefix] = phone_jid
                        _persist_lid_mapping(lid_prefix, phone_jid)
                        logger.info("Resolved LID %s to phone JID %s via msg history", lid_prefix, phone_jid)
                        return phone_jid
    except Exception as e:
        logger.warning("LID resolution via msg history failed: %s", e)
    return None

def _extract_from_openwa_payload(payload: dict) -> tuple:
    """Extract (body, from_number, has_attachment, raw_chat_id, media) from OpenWA webhook JSON."""
    event = payload.get("event", "")
    data = payload.get("data", payload)
    if event and event != "message.received":
        return ("", "", False, "", (None, None))
    # Never process our own outbound. If the gateway ever echoes a sent message as
    # message.received (fromMe=true), processing it would make the bot reply to
    # itself — at worst an assign/reply loop. Drop it.
    if isinstance(data, dict) and data.get("fromMe"):
        return ("", "", False, "", (None, None))
    body = ""
    if isinstance(data, dict):
        body = data.get("body", data.get("text", data.get("caption", "")))
        if isinstance(body, dict):
            body = body.get("text", "")
    body = str(body).strip()

    # Try multiple fields for sender identity: sender.id (ContactId), chatId, from, remoteJid
    raw_from = ""
    raw_chat_id = ""
    if isinstance(data, dict):
        raw_chat_id = data.get("chatId") or data.get("from") or ""
        raw_from = (
            data.get("sender", {}).get("id")
            or data.get("chatId")
            or data.get("from")
            or data.get("remoteJid")
            or ""
        )
    logger.info("Webhook RAW payload: %s", json.dumps(data, default=str)[:2000])

    # If raw_from is a LID, try to resolve to phone JID
    if "@lid" in raw_from:
        resolved = _resolve_lid(raw_from)
        if resolved:
            # Cache reverse mapping so send_whatsapp can fallback to @lid format
            set_lid_mapping(resolved, raw_chat_id or raw_from)
            raw_from = resolved
        else:
            # LID resolution failed (fresh session, no message history).
            # Still store the raw LID so send_whatsapp can try @lid fallback.
            fallback_jid = raw_from.split("@")[0] + "@c.us"
            set_lid_mapping(fallback_jid, raw_chat_id or raw_from)
            logger.info("LID resolution failed, stored raw LID fallback: %s -> %s", fallback_jid, raw_chat_id or raw_from)

    from app.utils.helpers import normalize_phone
    from_number = normalize_phone(raw_from.split("@")[0]) if raw_from else ""
    # OpenWA signals an attachment by including a `media` object (base64 payload),
    # NOT a `hasMedia`/`hasAttachment` boolean. Reading only the boolean meant
    # has_attachment was ALWAYS False, so `requires_attachment` tasks could never
    # be completed. Check the media object first.
    has_attachment = bool(data.get("media")) or bool(data.get("hasMedia", data.get("hasAttachment", False)))
    media_obj = data.get("media") if isinstance(data, dict) else None
    media_b64 = media_mime = media_name = None
    if isinstance(media_obj, dict):
        media_b64 = media_obj.get("data") or media_obj.get("base64")
        media_mime = media_obj.get("mimetype")
        media_name = media_obj.get("filename") or media_obj.get("name")
    return (body, from_number, has_attachment, raw_chat_id, (media_b64, media_mime, media_name))


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, db=Depends(get_db)):
    raw_bytes = await request.body()

    # Security: prefer HMAC signature verification (OpenWA signs payloads with the
    # secret registered on the webhook). Falls back to the legacy API-key header
    # check only when no signing secret is configured.
    if getattr(settings, "openwa_webhook_secret", ""):
        if not _verify_webhook_signature(raw_bytes, request.headers.get("x-openwa-signature", "")):
            logger.warning("Webhook rejected: invalid signature from %s",
                           request.client.host if request.client else "unknown")
            return {"status": "unauthorized"}
    else:
        expected_token = getattr(settings, "openwa_api_key", "")
        if expected_token:
            incoming_token = request.headers.get("x-webhook-token", request.headers.get("x-api-key", ""))
            if incoming_token and incoming_token != expected_token:
                logger.warning("Webhook rejected: invalid token from %s",
                               request.client.host if request.client else "unknown")
                return {"status": "unauthorized"}

    # Idempotency: ignore re-deliveries of a message we already handled.
    #
    # Prefer the WhatsApp message id carried IN the payload (`data.id`/`id`): it is
    # stable for a given message across every delivery. We must NOT trust the
    # gateway's per-delivery `x-openwa-idempotency-key` header — it is unique per
    # webhook registration AND per retry attempt, so when multiple webhooks (or
    # retries) fire for one message each delivery gets a different header value and
    # slips past dedup, making the bot reply and re-assign the task N times.
    #
    # Fallbacks: gateway header `msg_<id>` (only when it's not the constant
    # `_unknown` sentinel), then a content hash of the raw body.
    payload_msg_id = ""
    try:
        _pre = json.loads(raw_bytes) if raw_bytes else {}
        _pd = _pre.get("data", _pre) if isinstance(_pre, dict) else {}
        if isinstance(_pd, dict):
            payload_msg_id = str(_pd.get("id") or _pd.get("messageId") or _pd.get("waMessageId") or "")
    except Exception:
        pass

    header_key = (request.headers.get("x-openwa-idempotency-key")
                  or request.headers.get("x-openwa-delivery-id", ""))
    if payload_msg_id:
        idempotency_key = "wamid_" + payload_msg_id
    elif header_key and not header_key.endswith("_unknown"):
        idempotency_key = header_key
    else:
        idempotency_key = "body_" + hashlib.sha256(raw_bytes).hexdigest()[:16]
    if _is_duplicate_delivery(idempotency_key):
        logger.info("Webhook duplicate delivery ignored: %s", idempotency_key)
        return {"status": "duplicate"}

    content_type = request.headers.get("content-type", "")
    body = ""
    from_number = ""
    has_attachment = False
    raw_chat_id = ""

    media = (None, None, None)
    if "json" in content_type:
        try:
            raw = json.loads(raw_bytes) if raw_bytes else {}
        except Exception:
            raw = {}
        body, from_number, has_attachment, raw_chat_id, media = _extract_from_openwa_payload(raw)
    else:
        form_data = await request.form()
        body = form_data.get("Body", "").strip()
        from_number = form_data.get("From", "").replace("whatsapp:", "")
        num_media = int(form_data.get("NumMedia", 0))
        has_attachment = num_media > 0

    try:
        if not body and not has_attachment:
            return {"status": "empty"}

        # Detect language early so all handlers can translate responses
        lang = nlu_service._detect_language(body)

        emp_svc = EmployeeService(db)
        try:
            employee = emp_svc.get_by_whatsapp(from_number)
        except Exception as e:
            logger.error("Employee lookup failed for %s: %s", from_number, e)
            return {"status": "error", "detail": "employee lookup failed"}

        if not employee:
            return await _handle_unregistered(from_number, body, db, lang)

        task_mgr = TaskManager(db)
        # Track whether we found an employee for the error handler
        _emp_for_error = employee

        # Multi-attachment checklist: an inbound photo/file fills the next item.
        media_b64, media_mime, media_name = media
        if has_attachment:
            from app.services.attachment_service import AttachmentService
            att_svc = AttachmentService(db)
            active = att_svc.find_active_checklist_task(employee.id)
            if active:
                row, received, total = att_svc.record_media(active, media_b64, media_mime)
                if att_svc.is_complete(active.id):
                    active.status = TaskStatus.done
                    active.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    send_whatsapp(employee.whatsapp_number,
                        _t(f"🎉 All {total} photos received for \"{active.title}\". Marked done!", lang))
                    att_svc.forward_completed(active)
                else:
                    remaining = att_svc.remaining_items(active.id)
                    nxt = remaining[0] if remaining else "?"
                    send_whatsapp(employee.whatsapp_number,
                        _t(f"✅ Got \"{row.item_label}\" ({received}/{total}). Next: {nxt}", lang))
                return {"status": "ok", "intent": "CHECKLIST_PHOTO"}
            # No active checklist task. A standalone photo (no command text) from a
            # worker who has an attachment-required task pending is proof for it.
            # Workers may send MANY photos before typing 'done' — accumulate them
            # all and forward the whole set when the task is marked done.
            if not body:
                pend = task_mgr.get_pending_tasks(employee.id)
                needs = [t for t in pend if getattr(t, "requires_attachment", False)]
                _kind = "Photo" if _is_image(media_mime) else "File"
                if media_b64 and needs:
                    n = _add_proof_image(employee.id, media_b64, media_mime, media_name)
                    logger.info("Proof %s %s held for %s (task '%s')",
                                _kind.lower(), n, employee.name, needs[0].title)
                    send_whatsapp(employee.whatsapp_number,
                        _t(f"📎 {_kind} {n} saved. Send more, or reply 'done' to finish.", lang))
                    return {"status": "ok", "intent": "PROOF_HELD"}
                # Attachment with no pending attachment task — tell the worker instead
                # of silently dropping it (the common 'nothing forwarded' confusion).
                if media_b64 and not needs:
                    logger.info("%s from %s but no pending attachment task", _kind, employee.name)
                    send_whatsapp(employee.whatsapp_number,
                        _t(f"📎 Got your {_kind.lower()}, but you have no task that needs an attachment right now.", lang))
                    return {"status": "ok", "intent": "PHOTO_NO_TASK"}
            # Otherwise fall through to normal single-attachment handling.

        # Remember the language this employee writes in (positive signal only —
        # never downgrade to english on a short "done"/"ok"). Used later to
        # localize notifications we send TO them.
        if lang and lang != "english" and getattr(employee, "preferred_language", None) != lang:
            try:
                employee.preferred_language = lang
                db.commit()
            except Exception:
                db.rollback()

        # URL fetch — collapse newlines in body so multi-line URLs are caught.
        # Skip the shortcut when the message is actually a command/assignment that
        # merely contains a link (e.g. "@Raj check https://… and fix") or an
        # admin is assigning — otherwise the task is silently lost to a web fetch.
        flat_body = re.sub(r"\s+", "", body) if "http" in body.lower() else body
        url_match = re.search(r"https?://[^\s]+", flat_body)
        # Test the command signals on the body with the URL span REMOVED, so a
        # handle/email inside the link (twitter.com/@x, a@b.com) doesn't look like
        # an @mention and falsely suppress a genuine web-fetch.
        body_wo_url = re.sub(r"https?://[^\s]+", " ", body)
        _is_command = (
            bool(re.search(r"@\w+", body_wo_url))
            or re.search(r"\b(assign|delegate)\s+(to|kar|de)\b", body_wo_url.lower()) is not None
            or body.lower().startswith("edit task")
            or _is_escalate_command(body)
            or is_done_command(body_wo_url)
        )
        if _is_command:
            url_match = None
        if url_match:
            fetched = nlu_service.webfetch(url_match.group(0))
            if not fetched.startswith("❌"):
                lang = nlu_service._detect_language(body)
                answer = nlu_service.ask(f"Summarize this: {body}", fetched, lang)
                send_whatsapp(employee.whatsapp_number, f"🔍 *Web Fetch Result:*\n\n{answer}")
            else:
                send_whatsapp(employee.whatsapp_number, fetched)
            # CQ-5: Log web fetch conversations
            task_mgr = TaskManager(db)
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.help, language=lang)
            return {"status": "ok", "intent": "WEB_FETCH"}

        # Edit task command (before NLU — specific command format)
        if body.lower().startswith("edit task"):
            _handle_edit_command(body, employee, task_mgr, emp_svc, lang)
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.help, language=lang)
            return {"status": "ok", "intent": "EDIT_TASK"}

        # Self-service leave toggle (before NLU). While on leave the scheduler
        # sends no SOP tasks/reminders to them; "back" resumes.
        _leave = _leave_command(body)
        if _leave:
            employee.on_leave = (_leave == "leave")
            db.commit()
            if _leave == "leave":
                send_whatsapp(employee.whatsapp_number,
                    _t("🌴 Marked *on leave*. You won't get task reminders until you're back.\nType 'back' when you return.", lang))
            else:
                send_whatsapp(employee.whatsapp_number,
                    _t("✅ Welcome back! You're now *active* and will receive tasks again.", lang))
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.help, language=lang)
            return {"status": "ok", "intent": "LEAVE" if _leave == "leave" else "RETURN"}

        # Explicit "escalate" request (before NLU — keyword parser would treat it
        # as a generic question). Forces escalation straight to the admins.
        if _is_escalate_command(body):
            await _handle_trouble(employee, task_mgr, body, lang, db, force_escalate=True)
            return {"status": "ok", "intent": "ESCALATE"}

        # Parse intent
        try:
            _history = chat_memory.format_for_prompt(employee.id)
            parsed = nlu_service.parse(body, employee.name, employee.is_admin, history=_history)
            intent = parsed.get("intent", "HELP")
            lang = parsed.get("language", "english")
            entities = parsed.get("entities") or {}  # LLM may emit entities:null
        except Exception as e:
            logger.error("NLU parse failed for %s: %s", from_number, e)
            send_whatsapp(employee.whatsapp_number, "❌ System busy, please try again.")
            return {"status": "error", "detail": "nlu parse failed"}

        # Context-aware task completion over chat. A worker often reports/completes
        # a task in plain words ("previous day KOT is 10") instead of typing "done".
        # For non-command messages that aren't questions, match the message against
        # their pending tasks (LLM understands context; keyword echo is a fast path)
        # and complete the right one. Attachment tasks keep their photo flow.
        if (intent not in ("TASK_ASSIGN", "TASK_DONE", "REGISTER")
                and not _looks_like_question(body) and not _looks_like_trouble(body)
                and len(body.strip()) > 3):
            _pending = task_mgr.get_pending_tasks(employee.id)
            if _pending:
                _target, _ans = None, ""
                _kw = _match_task_by_title(body, _pending)
                if _kw:
                    _target, _ans = _kw, body
                else:
                    _c = nlu_service.classify_task_completion(
                        body, [{"id": t.id, "title": t.title} for t in _pending])
                    if _c.get("task_id"):
                        _target = next((t for t in _pending if str(t.id) == _c["task_id"]), None)
                        _ans = _c.get("answer") or body
                _ans_bad = _looks_like_trouble(_ans)  # LLM answer signalling not-done
                if _target and not _ans_bad and not getattr(_target, "requires_attachment", False):
                    if _complete_task_from_report(_target, _ans, body, employee, task_mgr, lang):
                        return {"status": "ok", "intent": "TASK_REPORT", "task_id": _target.id}

        if intent == "TASK_ASSIGN" and employee.is_admin:
            _handle_task_assign(body, employee, emp_svc, task_mgr, entities, lang)
        elif intent == "TASK_DONE":
            _handle_task_done(employee, task_mgr, lang, body, has_attachment, media)
        elif intent == "TROUBLE_HELP":
            await _handle_trouble(employee, task_mgr, body, lang, db)
        elif intent == "FOLLOW_UP":
            _handle_followup(body, employee, task_mgr, lang, db)
            # CQ-5: Log follow-up conversations
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.followup, language=lang)
        elif intent == "STATUS_CHECK":
            _handle_status_check(body, employee, task_mgr, emp_svc, lang)
            # CQ-5: Log status check conversations
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.status_check, language=lang)
        elif intent == "REGISTER":
            send_whatsapp(employee.whatsapp_number, _t("✅ You are already registered!", lang))
            # CQ-5: Log register attempt
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.help, language=lang)
        elif intent == "HELP":
            # Genuine "help" request vs general question (keyword fallback default)
            if any(w in body.lower() for w in ["help", "commands", "kya kar"]):
                _handle_help(employee, lang)
            else:
                reply = assistant_answer(body, employee, db, language=lang, history=_history)
                send_whatsapp(employee.whatsapp_number, reply)
                chat_memory.append(employee.id, "user", body)
                chat_memory.append(employee.id, "bot", reply)
            # CQ-5: Log help conversations
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.help, language=lang)
        else:
            reply = assistant_answer(body, employee, db, language=lang, history=_history)
            send_whatsapp(employee.whatsapp_number, reply)
            chat_memory.append(employee.id, "user", body)
            chat_memory.append(employee.id, "bot", reply)
            # CQ-5: Log general question conversations
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.help, language=lang)

        return {"status": "ok", "intent": intent, "language": lang}

    except Exception as e:
        logger.exception("Unhandled webhook error from %s: %s", from_number, e)
        try:
            emp = locals().get("_emp_for_error")
            if emp:
                send_whatsapp(emp.whatsapp_number, "❌ System error, please try again later.")
        except Exception:
            pass
        # SEC-8 fix: Don't leak internal error details to the client
        return {"status": "error", "detail": "An internal error occurred. Please try again later."}

async def _handle_unregistered(from_number: str, body: str, db, lang: str = "english"):
    """Messages from unknown numbers are IGNORED silently — no reply and no
    self-registration. Employees are added only from the dashboard or by an admin
    (no public self-signup over WhatsApp). Just log and drop."""
    logger.info("Ignoring message from unregistered number %s", from_number)
    return {"status": "ignored_unregistered"}

def _handle_task_assign(body, employee, emp_svc, task_mgr, entities, lang):
    target_name = entities.get("target_name") or extract_mention(body)
    if not target_name:
        send_whatsapp(employee.whatsapp_number,
            _t("⚠️ Who should I assign to? Use @mention.\n\n"
               "Example: @Raj server fix karo", lang))
        return

    target = emp_svc.get_by_name_or_mention(target_name)
    if not target:
        send_whatsapp(employee.whatsapp_number,
            _t(f"❌ '{target_name}' not found. Check the name or @mention.", lang))
        return

    due_date = extract_due_date(body)

    # ── LLM verification step: verify/correct parsed entities before sending ──
    if nlu_service.api_key:
        verified = nlu_service.verify_task_assign(body, entities)
        # Only override if LLM returned a valid target
        if verified.get("target_name") and verified["target_name"] != target_name:
            corrected_target = emp_svc.get_by_name_or_mention(verified["target_name"])
            if corrected_target:
                target = corrected_target
                target_name = verified["target_name"]
        priority = verified.get("priority") or entities.get("priority") or extract_priority(body) or "medium"
        task_desc = verified.get("task_description") or entities.get("task_description") or body
        follow_up_type = verified.get("follow_up_type") or entities.get("follow_up_type") or "none"
        interval_hours = verified.get("interval_hours") or entities.get("interval_hours")
    else:
        priority = entities.get("priority") or extract_priority(body) or "medium"
        task_desc = entities.get("task_description") or body
        follow_up_type = entities.get("follow_up_type", "none")
        interval_hours = entities.get("interval_hours")

    # Whitelist LLM-supplied enum values — an out-of-vocabulary priority
    # ("urgent"/"critical") or follow_up_type would raise ValueError in the enum
    # constructors and abort the whole assignment into the generic error path.
    if str(priority).lower() not in ("high", "medium", "low"):
        priority = "medium"
    if str(follow_up_type).lower() not in ("none", "periodic", "due_date"):
        follow_up_type = "none"

    # Notify admin about extracted follow-up if set
    if follow_up_type == "periodic" and interval_hours:
        if interval_hours < 1:
            mins = int(interval_hours * 60)
            fu_msg = f"🔄 Follow-up every {mins} minutes set for {target.name}."
        else:
            hrs = int(interval_hours)
            fu_msg = f"🔄 Follow-up every {hrs} hour{'s' if hrs > 1 else ''} set for {target.name}."
        send_whatsapp(employee.whatsapp_number, _t(fu_msg, lang))

    task = task_mgr.assign(
        admin_id=employee.id,
        target_id=target.id,
        title=task_desc,
        priority=priority,
        due_date=due_date,
        follow_up_type=follow_up_type if follow_up_type else "none",
        interval_hours=interval_hours,
        requires_attachment=extract_requires_attachment(body) or entities.get("requires_attachment", False),
    )

    # Notifications TO the target are localized to the target's own language;
    # confirmations back to the admin use the admin's message language (lang).
    target_lang = getattr(target, "preferred_language", "english") or "english"

    # Notify that attachment proof is required
    if task.requires_attachment:
        send_whatsapp(target.whatsapp_number,
            _t("📸 This task requires photo evidence when marking done.", target_lang))
        send_whatsapp(employee.whatsapp_number,
            _t(f"📸 Attachment proof required for: \"{task.title}\"", lang))

    due_text = f"Due: {due_date.strftime('%d %b %Y')}" if due_date else ""

    # F-13: Send interactive buttons with the task notification
    try:
        send_interactive_buttons(target.whatsapp_number,
            _t(f"📋 *New Task Assigned*\n\n"
               f"From: {employee.name}\n"
               f"Task: {task.title}\n"
               f"Priority: {task.priority.value.upper()}\n"
               f"{due_text}", target_lang),
            [
                {"id": "done", "title": "✅ Mark Done"},
                {"id": "help", "title": "❓ Need Help"},
            ])
    except Exception:
        # Fallback to plain text if interactive not supported
        send_whatsapp(target.whatsapp_number,
            _t(f"📋 *New Task Assigned*\n\n"
               f"From: {employee.name}\n"
               f"Task: {task.title}\n"
               f"Priority: {task.priority.value.upper()}\n"
               f"{due_text}\n\n"
               f"Reply 'done' when complete, or describe your issue for help.", target_lang))

    send_whatsapp(employee.whatsapp_number,
        _t(f"✅ Task assigned to {target.name}: \"{task.title}\"", lang))

    # BUG-8 fix: Log as inbound (admin sent the message)
    task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.assignment, task_id=task.id, language=lang)
    task_mgr.log_conversation(target.id, f"New task: {task.title}", Direction.outbound, MessageType.assignment, task_id=task.id, language=lang)

def employee_task_db(task_mgr):
    """The SQLAlchemy session behind a TaskManager (kept private elsewhere)."""
    return task_mgr.db


_DONE_STOPWORDS = {"done", "complete", "completed", "finished", "finish", "ho",
                   "gaya", "gya", "gyi", "kar", "diya", "kardiya", "task", "the",
                   "is", "kr", "hogya", "ho gaya", "mark", "marked"}


_QUESTION_WORDS = {"kya", "kaise", "kaisa", "kaha", "kahan", "kab", "kyu", "kyun", "kyon",
                   "how", "what", "why", "when", "where", "who", "which", "help", "madad",
                   "batao", "bata", "samajh", "kaise", "kese"}
_TROUBLE_WORDS = {"problem", "issue", "error", "stuck", "dikkat", "kharab", "broken",
                  "cannot", "cant", "fail", "failed", "nahi", "not", "band",
                  # not-done / incomplete markers — never auto-complete these
                  "pending", "baaki", "baki", "incomplete", "adhura", "adhoora",
                  "delay", "delayed", "later", "baad", "nhi"}

def _looks_like_question(body: str) -> bool:
    if "?" in (body or ""):
        return True
    return bool(set(re.findall(r"\w+", (body or "").lower())) & _QUESTION_WORDS)

def _looks_like_trouble(body: str) -> bool:
    return bool(set(re.findall(r"\w+", (body or "").lower())) & _TROUBLE_WORDS)


def _complete_task_from_report(task, answer: str, body: str, employee, task_mgr, lang: str) -> bool:
    """Mark a task done from a plain-chat report (no 'done' keyword). Records the
    reported value and forwards it to the assigner. Returns True if completed."""
    done_task, status = task_mgr.mark_done(employee.id, task_id=task.id, has_attachment=False)
    if not (done_task and status == "Success"):
        return False
    note = (answer or body or "").strip()
    send_whatsapp(employee.whatsapp_number,
        _t(f"✅ Noted for '{done_task.title}': {note}\nMarked as done. 🎉", lang))
    assigner = task_mgr.emp_svc.get_by_id(done_task.assigned_by_id)
    if assigner:
        alang = getattr(assigner, "preferred_language", "english") or "english"
        send_whatsapp(assigner.whatsapp_number,
            _t(f"✅ {employee.name} completed '{done_task.title}'\nReported: {note}", alang))
    task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.reply,
                              task_id=done_task.id, language=lang)
    return True


def _match_task_by_title(body: str, pending: list):
    """Pick the pending task whose title the message names, e.g.
    'cold room tempreature record done' -> that task. Returns the task on a
    confident, unambiguous match, else None (caller then asks 'which one?').

    Scores by how many meaningful title words appear in the message. Requires the
    best match to cover most of the title AND clearly beat the runner-up, so a
    vague message doesn't silently complete the wrong task."""
    words = set(re.findall(r"\w+", (body or "").lower())) - _DONE_STOPWORDS
    if not words:
        return None
    scored = []
    for t in pending:
        title_words = [w for w in re.findall(r"\w+", (t.title or "").lower()) if len(w) > 2]
        if not title_words:
            continue
        hit = sum(1 for w in title_words if w in words)
        coverage = hit / len(title_words)
        scored.append((hit, coverage, t))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    best = scored[0]
    second = scored[1] if len(scored) > 1 else (0, 0.0, None)
    # Accept a DOMINANT match: it must name >=2 meaningful title words (or fully
    # name a short title) AND strictly out-hit every other pending task, so the
    # words uniquely point at one task. A vague 1-word overlap stays ambiguous and
    # the caller falls back to asking 'which one?'.
    dominant = best[0] >= 2 and best[0] > second[0]
    short_full = best[1] >= 0.99 and best[0] > second[0]
    if dominant or short_full:
        return best[2]
    return None


def _handle_task_done(employee, task_mgr, lang, body="", has_attachment=False, media=(None, None, None)):
    """F-1: Enhanced — supports 'done 2' to mark specific task, plus mandatory attachments."""
    task_num = extract_task_number(body)
    media_b64, media_mime, media_name = (media + (None, None, None))[:3] if media else (None, None, None)
    # Gather ALL proof attachments (photos AND documents): any sent earlier
    # (accumulated in Redis) plus one attached to this very 'done' message.
    # We forward the whole set to the admin on completion.
    proof_imgs = _get_proof_images(employee.id)
    if media_b64:
        proof_imgs.append((media_b64, media_mime, media_name))
    if proof_imgs:
        has_attachment = True

    from app.services.attachment_service import AttachmentService
    att_svc = AttachmentService(employee_task_db(task_mgr))
    active = att_svc.find_active_checklist_task(employee.id)
    if active and not has_attachment:
        remaining = att_svc.remaining_items(active.id)
        if remaining:
            send_whatsapp(employee.whatsapp_number,
                _t("⚠️ Still need photos for: " + ", ".join(remaining) +
                   ".\nSend them one at a time.", lang))
            return

    if task_num:
        task, status = task_mgr.mark_done(employee.id, task_number=task_num, has_attachment=has_attachment)
    else:
        # Check if employee has multiple pending tasks
        pending = task_mgr.get_pending_tasks(employee.id)
        if len(pending) > 1:
            # Match by task NAME, e.g. "cold room tempreature record done" -> that
            # task, so workers don't have to count to "done N".
            matched = _match_task_by_title(body, pending)
            if matched:
                task, status = task_mgr.mark_done(employee.id, task_id=matched.id, has_attachment=has_attachment)
            else:
                msg = _t("📋 *Multiple pending tasks — which one is done?*", lang) + "\n\n"
                for i, t in enumerate(pending, 1):
                    msg += f"{i}. {t.title} [{t.priority.value}]\n"
                msg += _t("\nReply with the task name + 'done', or 'done 1' / 'done 2'.", lang)
                send_whatsapp(employee.whatsapp_number, msg)
                return
        else:
            task, status = task_mgr.mark_done(employee.id, has_attachment=has_attachment)

    if status == "Missing attachment":
        send_whatsapp(employee.whatsapp_number,
            _t(f"⚠️ Task \"{task.title}\" needs proof (photo/video/document).\n"
               "Please reply with attachment.", lang))
        return

    if task and status == "Success":
        send_whatsapp(employee.whatsapp_number,
            _t(f"✅ '{task.title}' marked as done! Great work 🎉", lang))
        assigner = task_mgr.emp_svc.get_by_id(task.assigned_by_id)
        if assigner:
            assigner_lang = getattr(assigner, "preferred_language", "english") or "english"
            # Forward ALL collected proof photos to the assigner (admin). A
            # requires_attachment task must reach the admin AS the photos, not
            # just a text line — otherwise the proof is silently dropped.
            if proof_imgs and getattr(task, "requires_attachment", False):
                from app.services.whatsapp import send_whatsapp_attachment
                total = len(proof_imgs)
                logger.info("Forwarding %s proof attachment(s) for '%s' to admin %s",
                            total, task.title, assigner.name)
                send_whatsapp(assigner.whatsapp_number,
                    _t(f"✅ {employee.name} completed: \"{task.title}\" — {total} attachment(s)", assigner_lang))
                for i, item in enumerate(proof_imgs, 1):
                    b64, mime, name = (item + (None, None, None))[:3]
                    send_whatsapp_attachment(
                        assigner.whatsapp_number,
                        _t(f"📎 {task.title} ({i}/{total})", assigner_lang),
                        b64 or "", mime, name)
                # Only clear once the photos were actually forwarded — completing a
                # NON-attachment task must not discard photos held for a pending
                # attachment task.
                _clear_proofs(employee.id)
            else:
                send_whatsapp(assigner.whatsapp_number,
                    _t(f"✅ {employee.name} completed: \"{task.title}\"", assigner_lang))
        task_mgr.log_conversation(employee.id, "done", Direction.inbound, MessageType.reply, task_id=task.id, language=lang)
    else:
        send_whatsapp(employee.whatsapp_number,
            _t("⚠️ No pending task found or wrong number. Type 'my tasks' to check.", lang))

async def _handle_trouble(employee, task_mgr, body, lang, db, force_escalate=False):
    from app.routers.settings import get_bool_setting
    # force_escalate is set when the user explicitly typed "escalate" — honor it
    # by skipping the KB search and going straight to the admins.
    direct_escalation = force_escalate or get_bool_setting(db, "direct_escalation")
    include_details = get_bool_setting(db, "escalation_notify_employee_details")

    kb_svc = KBService(db)

    # Only search KB if direct escalation is disabled
    if not direct_escalation:
        results = kb_svc.search(body, language=lang)
        if results and results[0].get("similarity", 0) > 0.3:
            top = results[0]
            summary = nlu_service.generate_answer(body, top["content"], lang)
            send_whatsapp(employee.whatsapp_number,
                _t(f"🔍 *Solution found:*\n\n{summary}\n\n"
                   f"---\nIf this does not help, type 'escalate'.", lang))
            task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.trouble, language=lang)
            kb_svc.add_past_resolution(body, summary, language=lang)
            return

    # If we get here, either direct_escalation is ON, or KB search failed/was skipped via "escalate" keyword
    # BUG-C6 fix: Match the help request to the most relevant task using word overlap scoring,
    # instead of blindly using pending_tasks[0]
    pending_tasks = task_mgr.get_pending_tasks(employee.id)
    # Route by the task's assigner. When nothing is pending (e.g. the task was
    # already marked done), fall back to the employee's recent tasks so the
    # escalation still reaches the assigner instead of blasting every admin.
    candidate_tasks = pending_tasks or task_mgr.get_recent_tasks(employee.id)
    task_id = None
    matched_task = None

    if candidate_tasks:
        if len(candidate_tasks) == 1:
            # Only one task — it's obviously the one they need help with
            task_id = candidate_tasks[0].id
            matched_task = candidate_tasks[0]
        else:
            # Multiple tasks — score each task title against the help message
            body_words = set(body.lower().split())
            best_score = 0
            for t in candidate_tasks:
                title_words = set(t.title.lower().split())
                # Count overlapping words (exclude very short/common words)
                overlap = sum(1 for w in title_words if len(w) > 2 and w in body_words)
                if overlap > best_score:
                    best_score = overlap
                    matched_task = t
                    task_id = t.id
            # If no meaningful overlap (score < 2), default to most recent task
            # and include a note in the ticket
            if best_score < 2:
                matched_task = candidate_tasks[0]
                task_id = candidate_tasks[0].id
    
    ticket = EscalationTicket(
        employee_id=employee.id,
        task_id=task_id,
        original_query=body,
        bot_attempted_solution="Direct escalation" if direct_escalation else "KB search returned no results",
        status=EscalationStatus.open,
    )
    db.add(ticket)
    db.commit()

    # CQ-5: Log escalation conversation
    task_mgr.log_conversation(employee.id, body, Direction.inbound, MessageType.escalation,
                              task_id=task_id, language=lang)

    send_whatsapp(employee.whatsapp_number,
        _t("❌ Notifying the admin.\nSomeone will help you shortly.", lang))

    # Notify ONLY the matched task's own admin (its assigner), not every admin.
    # Fall back to all admins only when the escalation isn't tied to any task.
    task_admin = task_mgr.emp_svc.get_by_id(matched_task.assigned_by_id) if matched_task else None
    admins = task_mgr.emp_svc.resolve_escalation_recipients(task_admin)

    # Build detailed admin message (always English for admin)
    admin_msg = (
        f"🆘 *Escalation Alert*\n\n"
        f"*{employee.name}* needs help!\n"
        f"💬 *Query:* {body}\n\n"
        f"🎫 *Ticket #:* {ticket.id[:8]}\n"
    )

    # BUG-C6: Show which task was matched (if any)
    if matched_task:
        admin_msg += f"📌 *Related Task:* {matched_task.title} [{matched_task.priority.value}]\n"
    
    if include_details:
        admin_msg += f"📞 *Contact:* {employee.whatsapp_number}\n"
        admin_msg += f"🏢 *Dept/Role:* {employee.department} / {employee.role}\n"
        
        if pending_tasks:
            admin_msg += f"\n📋 *All Pending Tasks ({len(pending_tasks)}):*\n"
            for t in pending_tasks[:3]:
                marker = " ← likely" if t.id == task_id and len(pending_tasks) > 1 else ""
                admin_msg += f"• {t.title} [{t.priority.value}]{marker}\n"
            if len(pending_tasks) > 3:
                admin_msg += f"  ...and {len(pending_tasks) - 3} more\n"
        else:
            admin_msg += f"\n📋 *Current Tasks:* None\n"

    for admin in admins:
        send_whatsapp(admin.whatsapp_number, admin_msg)


def _handle_followup(body, employee, task_mgr, lang, db):
    if employee.is_admin:
        tasks = task_mgr.get_all_pending()
        if not tasks:
            send_whatsapp(employee.whatsapp_number, _t("✅ All tasks are complete!", lang))
            return
        msg = _t("📋 *All Pending Tasks:*", lang) + "\n\n"
        for t in tasks[:10]:
            assignee = task_mgr.emp_svc.get_by_id(t.assigned_to_id)
            name = assignee.name if assignee else "Unknown"
            msg += f"• {t.title} → {name} [{t.priority.value}]\n"
        if len(tasks) > 10:
            msg += _t(f"\n...and {len(tasks) - 10} more", lang)
        send_whatsapp(employee.whatsapp_number, msg)
    else:
        tasks = task_mgr.get_pending_tasks(employee.id)
        if not tasks:
            send_whatsapp(employee.whatsapp_number, _t("✅ You have no pending tasks.", lang))
        else:
            msg = _t(f"📋 *Pending tasks:*", lang) + "\n\n"
            for i, t in enumerate(tasks, 1):
                due = f" ({_t('Due', lang)}: {t.due_date.strftime('%d %b')})" if t.due_date else ""
                msg += f"{i}. {t.title} [{t.priority.value}]{due}\n"
            send_whatsapp(employee.whatsapp_number, msg)

def _handle_status_check(body, employee, task_mgr, emp_svc, lang):
    text_lower = body.lower()
    if employee.is_admin and any(w in text_lower for w in ["all", "team", "sabka", "sab", "every"]):
        tasks = task_mgr.get_all_pending()
        if not tasks:
            send_whatsapp(employee.whatsapp_number, _t("✅ All tasks are complete!", lang))
            return
        msg = _t("📋 *Team Pending Tasks:*", lang) + "\n\n"
        for t in tasks[:15]:
            assignee = emp_svc.get_by_id(t.assigned_to_id)
            name = assignee.name if assignee else "Unknown"
            msg += f"• {t.title} → {name} [{t.priority.value}]\n"
        send_whatsapp(employee.whatsapp_number, msg)
    else:
        tasks = task_mgr.get_pending_tasks(employee.id)
        if not tasks:
            send_whatsapp(employee.whatsapp_number, _t("✅ You have no pending tasks.", lang))
        else:
            msg = _t("📋 *Your pending tasks:*", lang) + "\n\n"
            for i, t in enumerate(tasks, 1):
                due = f" ({_t('Due', lang)}: {t.due_date.strftime('%d %b')})" if t.due_date else ""
                msg += f"{i}. {t.title} [{t.priority.value}]{due}\n"
            send_whatsapp(employee.whatsapp_number, msg)

def _handle_help(employee, lang="english"):
    """BUG-4 fix: This handler is now actually called."""
    if employee.is_admin:
        send_whatsapp(employee.whatsapp_number,
            _t("🤖 *WhatsApp Agent — Admin Commands*\n\n"
               "📝 *Assign task:* @name task description due date priority\n"
               "  Example: @Raj fix server bug by Friday high priority\n\n"
               "📸 *Require photo proof:* add 'with photo' / 'attachment' / 'send photo'\n"
               "  Example: @Raj clean kitchen with photo\n\n"
               "✅ *Employee replies done/ho gaya* → auto-marks complete\n\n"
               "❓ *Help/Stuck* → bot searches KB, escalates to you\n\n"
               "📋 *My team tasks:* 'all tasks', 'team pending', 'sabka status'\n\n"
               "🔄 *Follow up:* 'follow up', 'check all pending'\n\n"
               "🆘 *Escalations notified to you automatically*", lang))
    else:
        send_whatsapp(employee.whatsapp_number,
            _t("🤖 *WhatsApp Agent — Employee Commands*\n\n"
               "✅ *Done:* 'done', 'ho gaya', 'complete', 'kar diya'\n"
               "  Multiple tasks? 'done 1', 'done 2'\n\n"
               "❓ *Help:* 'stuck', 'error', 'samajh nahi aaya', 'help'\n\n"
               "📋 *My tasks:* 'my tasks', 'pending', 'kya karna hai'\n\n"
               "🆕 *Register:* 'register my name is <your name>'\n\n"
               "Reply to task messages with any issue and bot will try to help!", lang))

def _handle_edit_command(body: str, employee, task_mgr, emp_svc, lang: str):
    """Handle 'edit task <number> <field> <value>' command."""
    # Pattern: edit task <number> <field> <value>
    match = re.match(r"edit task\s+(\d+)\s+(\S+)\s+(.+)", body, re.IGNORECASE)
    if not match:
        send_whatsapp(employee.whatsapp_number,
            _t("❌ Format: edit task <number> <field> <value>\n"
               "Example: edit task 1 status blocked\n"
               "Fields: status, priority, due, title, desc, assign", lang))
        return

    task_num = int(match.group(1))
    field = match.group(2).lower()
    value = match.group(3).strip()

    # Validate field name
    valid_fields = {"status", "priority", "due", "title", "desc", "assign"}
    if field not in valid_fields:
        send_whatsapp(employee.whatsapp_number,
            _t(f"❌ Invalid field '{field}'. Options: {', '.join(sorted(valid_fields))}", lang))
        return

    # Get the task by number. IMPORTANT: number against the SAME ordered list the
    # admin was shown ('all tasks'/'team pending' = get_all_pending), not
    # get_all_tasks (which is assigned_at-desc) — otherwise 'edit task 1' edits a
    # different task than the one displayed as #1.
    if employee.is_admin:
        tasks = task_mgr.get_all_pending()
        task = tasks[task_num - 1] if 1 <= task_num <= len(tasks) else None
    else:
        tasks = task_mgr.get_pending_tasks(employee.id)
        if 1 <= task_num <= len(tasks):
            task = tasks[task_num - 1]
        else:
            send_whatsapp(employee.whatsapp_number,
                _t(f"❌ Task #{task_num} not found. Use 'my tasks' to see your tasks.", lang))
            return

    if not task:
        send_whatsapp(employee.whatsapp_number,
            _t(f"❌ Task #{task_num} not found.", lang))
        return

    # Permission check: non-admin can only edit status
    if not employee.is_admin and field != "status":
        send_whatsapp(employee.whatsapp_number,
            _t("❌ Only admin can change that field.", lang))
        return

    # Build update dict
    updates = {}
    field_display = field

    if field == "status":
        allowed = ["pending", "in_progress", "done", "blocked", "escalated"]
        if value not in allowed:
            send_whatsapp(employee.whatsapp_number,
                _t(f"❌ Invalid status '{value}'. Options: {', '.join(allowed)}", lang))
            return
        # Don't let 'edit task N status done' bypass the photo-proof requirement —
        # an attachment task must be completed through the normal 'done' + photo
        # flow so the proof reaches the admin.
        if value == "done" and getattr(task, "requires_attachment", False):
            send_whatsapp(employee.whatsapp_number,
                _t(f"⚠️ \"{task.title}\" needs photo proof. Send the photo(s) then reply 'done' — "
                   "it can't be closed via edit.", lang))
            return
        updates["status"] = value
        field_display = "status"

    elif field == "priority":
        allowed = ["high", "medium", "low"]
        if value not in allowed:
            send_whatsapp(employee.whatsapp_number,
                _t(f"❌ Invalid priority '{value}'. Options: {', '.join(allowed)}", lang))
            return
        updates["priority"] = value

    elif field == "due":
        due_date, err = parse_edit_due_date(value)
        if err:
            send_whatsapp(employee.whatsapp_number, _t(f"❌ {err}", lang))
            return
        if due_date is None:
            updates["_clear_due_date"] = True
        else:
            updates["due_date"] = due_date

    elif field == "title":
        if len(value) < 2:
            send_whatsapp(employee.whatsapp_number,
                _t("❌ Title too short (min 2 chars).", lang))
            return
        updates["title"] = value

    elif field == "desc":
        updates["description"] = value

    elif field == "assign":
        target = emp_svc.get_by_name_or_mention(value)
        if not target:
            send_whatsapp(employee.whatsapp_number,
                _t(f"❌ Employee '{value}' not found. Use name or @mention.", lang))
            return
        updates["assigned_to_id"] = target.id

    updated = task_mgr.update_task(task.id, updates)
    if not updated:
        send_whatsapp(employee.whatsapp_number,
            _t("❌ Failed to update task.", lang))
        return

    send_whatsapp(employee.whatsapp_number,
        _t(f"✅ Task #{task_num} {field_display} updated to '{value}'", lang))

    # If reassigned, notify the new assignee
    if field == "assign" and target:
        send_whatsapp(target.whatsapp_number,
            _t(f"📋 *New Task Reassigned to You*\n\n"
               f"Task: {updated.title}\n"
               f"Priority: {updated.priority.value.upper()}", lang))
