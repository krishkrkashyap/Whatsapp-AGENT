"""End-to-end system test for the Baileys-migrated WhatsApp bot.

Run inside the backend container:
    docker exec crusty-backend python test_system.py

Checks: DB/Redis/gateway health, Baileys session ready, backend<->gateway auth,
outbound text + document, and inbound text + media download from the test phone.
Sends real WhatsApp messages to TEST_NUMBER (you will receive them).
"""
import os
import sys
import time
import httpx

from app.config import settings
from app.services.openwa_session import get_active_session_id
from app.services.whatsapp import send_whatsapp, send_whatsapp_document

TEST_NUMBER = os.environ.get("TEST_NUMBER", "").strip()  # E.164, e.g. +9199...
if not TEST_NUMBER:
    sys.exit("Set TEST_NUMBER env var (E.164, e.g. +9199...) before running.")
TEST_CHAT = TEST_NUMBER.lstrip("+") + "@c.us"

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def gw(path, method="GET"):
    url = f"{settings.openwa_base_url}/{path.lstrip('/')}"
    headers = {"X-API-Key": settings.openwa_api_key, "Content-Type": "application/json"}
    return httpx.request(method, url, headers=headers, timeout=20)

def main():
    print("=" * 60)
    print("WhatsApp Bot — Full System Test")
    print("=" * 60)

    # 1. Backend deep health (DB, Redis, gateway)
    try:
        h = httpx.get("http://localhost:8000/health/deep", timeout=10).json()
        check("Backend health", h.get("status") == "ok", str(h))
    except Exception as e:
        check("Backend health", False, str(e))

    sid = get_active_session_id()
    check("Active session id resolved", bool(sid), sid)

    # 2. Gateway auth + session ready
    try:
        r = gw(f"sessions/{sid}")
        j = r.json()
        check("Gateway auth (api key synced)", r.status_code == 200, f"HTTP {r.status_code}")
        check("Session ready", j.get("status") == "ready",
              f"status={j.get('status')} phone={j.get('phone')}")
    except Exception as e:
        check("Gateway auth + session", False, str(e))

    # 3. Webhook registered -> backend
    try:
        wl = gw(f"sessions/{sid}/webhooks").json()
        reg = any("backend:8000/webhook" in (w.get("url") or "") and w.get("active") for w in wl)
        check("Inbound webhook registered", reg, f"{len(wl)} webhook(s)")
    except Exception as e:
        check("Inbound webhook registered", False, str(e))

    # 4. Outbound text
    mid = send_whatsapp(TEST_NUMBER, "✅ System test: text send OK (ignore)")
    check("Outbound text", mid not in ("error",), f"result={mid}")

    # 5. Outbound document (xlsx)
    xlsx = (b"PK\x03\x04" + b"\x00" * 40)  # minimal bytes; just proves the doc path sends
    dmid = send_whatsapp_document(TEST_NUMBER, "system_test.xlsx", xlsx,
                                  caption="✅ System test: document send OK (ignore)")
    check("Outbound document", dmid not in ("error",), f"result={dmid}")

    # 6. Inbound: recent messages from the test phone + media download
    try:
        r = gw(f"sessions/{sid}/messages?limit=25&downloadMedia=true")
        arr = r.json()
        arr = arr if isinstance(arr, list) else arr.get("data", arr.get("messages", []))
        mine = [m for m in arr if TEST_CHAT.split("@")[0] in str(m.get("from", ""))
                and m.get("direction") == "incoming"]
        check("Inbound messages received", len(mine) > 0, f"{len(mine)} from test phone")
        texts = [m for m in mine if (m.get("type") in (None, "text", "chat"))]
        medias = [m for m in mine if m.get("type") in ("image", "video", "document", "audio")]
        # media bytes present?
        def mbytes(m):
            md = m.get("media") or m.get("mediaData") or {}
            d = md.get("data") or md.get("base64") or ""
            return len(d)
        got_media = [m for m in medias if mbytes(m) > 0]
        check("Inbound text present", len(texts) > 0, f"{len(texts)} text msg(s)")
        check("Inbound MEDIA downloaded", len(got_media) > 0,
              "; ".join(f"{m.get('type')} {mbytes(m)}B" for m in got_media[:4]) or "no media with bytes — send a photo/doc first")
    except Exception as e:
        check("Inbound check", False, str(e))

    # Summary
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    print("=" * 60)
    sys.exit(0 if passed == len(results) else 1)

if __name__ == "__main__":
    main()
