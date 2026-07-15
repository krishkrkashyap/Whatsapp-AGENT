import re
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser


def normalize_phone(raw) -> str:
    """Canonical WhatsApp number form: '+<countrycode><national>' (India-default).

    THE single source of truth for phone normalization — used by CSV import,
    XLSX/SOP import, the dashboard create/update forms, the webhook sender id,
    and self-registration. Before this existed each entry point normalized
    differently (some prepended a bare '+', some added '91' for 10-digit
    numbers), so the same person landed in the DB twice under '+9794164362'
    AND '+919794164362', and inbound WhatsApp messages (always '+91…') failed
    to match the bare-'+' rows.

    Rules:
      - strip everything but digits
      - drop a leading international '00' prefix
      - '0XXXXXXXXXX' (11 digits, leading 0) -> 91 + the 10 national digits
      - bare 10-digit national number -> assume India, prefix 91
      - anything already carrying a country code is kept as-is
    Returns '' for empty/garbage input.
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    elif len(digits) == 10:
        digits = "91" + digits
    return "+" + digits


def extract_mention(text: str) -> str | None:
    """Extract @username from text."""
    match = re.search(r"@(\w+)", text)
    return match.group(1) if match else None

def extract_priority(text: str) -> str | None:
    text_lower = text.lower()
    if "high" in text_lower or "urgent" in text_lower or "jaldi" in text_lower:
        return "high"
    if "low" in text_lower or "kam priority" in text_lower:
        return "low"
    if "medium" in text_lower:
        return "medium"
    return None

def extract_due_date(text: str) -> datetime | None:
    """Try to extract a due date from text. Handles relative dates like 'tomorrow', 'Friday'."""
    try:
        text_lower = text.lower()
        now = datetime.now(timezone.utc)

        if "today" in text_lower or "aaj" in text_lower:
            return now
        if "tomorrow" in text_lower or "kal" in text_lower:
            return now + timedelta(days=1)
        if "next week" in text_lower:
            return now + timedelta(days=7)

        # BUG-C7 fix: Handle ALL 7 day names (was only Friday and Monday)
        day_map = {
            "monday": 0, "somwar": 0, "somvar": 0,
            "tuesday": 1, "mangalwar": 1, "mangalvar": 1,
            "wednesday": 2, "budhwar": 2, "budhvar": 2,
            "thursday": 3, "guruwar": 3, "guruvar": 3, "brihaspativar": 3,
            "friday": 4, "shukrawar": 4, "shukravar": 4,
            "saturday": 5, "shaniwar": 5, "shanivar": 5,
            "sunday": 6, "raviwar": 6, "ravivar": 6, "itwaar": 6,
        }
        for word, target_day in day_map.items():
            if word in text_lower:
                days_ahead = target_day - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                return now + timedelta(days=days_ahead)

        # Try standard date parsing — but ONLY on tokens that actually look like
        # a date. The old code ran dateparser on every word, so bare numbers in
        # a task ("fix bug 11", "ticket 2024") were silently turned into due
        # dates. Require a date separator (/, -, .) or a month name.
        months = ("jan", "feb", "mar", "apr", "may", "jun",
                  "jul", "aug", "sep", "oct", "nov", "dec")
        for word in text.split():
            w = word.lower().strip(",")
            looks_like_date = (
                re.search(r"\d[/\-.]\d", w)          # 12/05, 2026-05-19
                or any(m in w for m in months)        # 19may, may
            )
            if not looks_like_date:
                continue
            try:
                parsed = dateparser.parse(word, fuzzy=False)
                if not parsed:
                    continue
                # dateparser returns a naive datetime; make it tz-aware BEFORE
                # comparing, otherwise "naive vs aware" raises TypeError (which
                # the old code silently swallowed, so dates never parsed).
                parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed >= now - timedelta(days=1):
                    return parsed
            except (ValueError, OverflowError):
                continue
    except Exception:
        pass
    return None

def extract_requires_attachment(text: str) -> bool:
    """Check if text requires attachment evidence (send pic, click photo, etc.)."""
    text_lower = text.lower()
    attach_hints = [
        # picture / photo verbs
        "send pic", "send photo", "send snap", "send image", "send picture",
        "click pic", "click photo", "click picture",
        "share pic", "share photo", "share image",
        "upload pic", "upload photo", "upload image",
        "with pic", "with photo", "with image", "with proof", "with attachment",
        # attachment keyword (this was missing — 'send attachment' / 'attachment
        # required / necessary / mandatory' never triggered)
        "attachment", "attach pic", "attach photo", "attach image",
        # proof / evidence
        "photo proof", "pic proof", "send proof", "send evidence",
        "proof", "evidence",
        # Hindi / Hinglish
        "photo bhej", "pic bhej", "photo dal", "photo daal", "photo chahiye",
        "photo zaroori", "photo zaruri", "photo lazmi", "photo bhejo", "photo bhejna",
        "saboot", "sboot", "sabut", "tasveer",
    ]
    return any(hint in text_lower for hint in attach_hints)


# Done-command phrases (Hindi/Hinglish/Gujarati variants). Spaces optional so
# "hogya1", "ho gya 1", "kardiya 2" all parse. Shared by extract_task_number and
# the NLU done-intent matcher so both stay in sync.
_DONE_PHRASES = [
    "done", "complete", "completed", "finish", "finished", "mark done",
    # ho gaya family: ho gaya/gya/gyi/gai/gayi, hogaya/hogya/hogyi/hogai
    "ho gaya", "ho gya", "ho gyi", "ho gai", "ho gayi", "ho gaye",
    "hogaya", "hogya", "hogyi", "hogai", "hogayi", "hogaye",
    # kar diya family: kar/kr/ker + diya/dia/diya
    "kar diya", "kardiya", "kar dia", "kardia", "kr diya", "krdiya",
    "kar diye", "kardiye", "ho gual",
    # kia/kiya
    "kiya", "kia", "kar liya", "karliya",
    # Gujarati: thai gayu / puru thayu / puri thai
    "thai gayu", "thai gyu", "puru thayu", "puri thai", "puru thai", "thai gayu",
]
# Build a regex alternation, longest first so "ho gaya" wins over "ho".
_DONE_ALT = "|".join(re.escape(p) for p in sorted(set(_DONE_PHRASES), key=len, reverse=True))
# done-then-number ("done 2", "hogya1", "ho gya #3") OR number-then-done ("2 done", "task 1 hogya")
_TASKNUM_RE = re.compile(
    rf"(?:(?:{_DONE_ALT})\s*#?\s*(\d+))|(?:(\d+)\s*(?:{_DONE_ALT}))",
    re.IGNORECASE,
)


def extract_task_number(text: str) -> int | None:
    """Extract a task number from a done command — 'done 2', 'complete #3',
    'hogya1', 'ho gya 1', 'kardiya 2', '2 done', etc."""
    m = _TASKNUM_RE.search((text or "").lower())
    if m:
        return int(m.group(1) or m.group(2))
    return None


# Word-boundary match for a done phrase, tolerating a glued trailing number
# ("hogya1") which would otherwise break the right-hand \b.
_DONE_WORD_RE = re.compile(rf"\b(?:{_DONE_ALT})\d*\b", re.IGNORECASE)


def is_done_command(text: str) -> bool:
    """True when the message is a task-completion command in any supported
    Hindi/Hinglish/Gujarati/English variant (incl. 'done N' / 'hogya1' forms)."""
    t = (text or "").lower()
    if extract_task_number(t) is not None:
        return True
    return bool(_DONE_WORD_RE.search(t))

def parse_edit_due_date(value: str) -> tuple | None:
    """Parse due date from WhatsApp edit command value.
    Returns (datetime_obj, None) on success or (None, error_msg) on failure.
    Handles: tomorrow, today, YYYY-MM-DD, clear/none."""
    text = value.strip().lower()
    now = datetime.now(timezone.utc)
    if text in ("tomorrow", "kal"):
        return (now + timedelta(days=1), None)
    if text in ("today", "aaj"):
        return (now, None)
    if text in ("clear", "none", "null", "remove", "delete"):
        return (None, None)  # None value means clear
    try:
        parsed = dateparser.parse(text, fuzzy=False)
        if parsed:
            return (parsed.replace(tzinfo=timezone.utc), None)
    except Exception:
        pass
    return (None, "Invalid date. Use: tomorrow, today, YYYY-MM-DD, or clear")
