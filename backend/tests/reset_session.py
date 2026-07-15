"""Reset OpenWA session and get fresh QR code."""
import sys; sys.path.insert(0, '/app')
import httpx, json, time, base64
from app.config import settings

h = {"X-API-Key": settings.openwa_api_key, "Content-Type": "application/json"}

# 1. Delete current session
old_sid = settings.openwa_session_id
r = httpx.delete(f"{settings.openwa_base_url}/sessions/{old_sid}", headers=h, timeout=15)
print(f"1. Delete old session ({old_sid}): {r.status_code}")

# 2. Create new session
r2 = httpx.post(f"{settings.openwa_base_url}/sessions", headers=h, json={"name": "wabot"}, timeout=15)
sid = r2.json().get("id")
print(f"2. Created new session: {sid}")

# 3. Start it
r3 = httpx.post(f"{settings.openwa_base_url}/sessions/{sid}/start", headers=h, timeout=120)
print(f"3. Start: {r3.status_code} status={r3.json().get('status','?')}")

# 4. Register webhook
r4 = httpx.post(f"{settings.openwa_base_url}/sessions/{sid}/webhooks", headers=h,
    json={"url": "http://backend:8000/webhook/whatsapp", "events": ["message.*"]}, timeout=15)
print(f"4. Webhook: {r4.status_code} active={r4.json().get('active','?')}")

# 5. Wait for QR generation
print("5. Waiting for QR generation...")
time.sleep(10)

# 6. Get QR
r5 = httpx.get(f"{settings.openwa_base_url}/sessions/{sid}/qr", headers=h, timeout=30)
data = r5.json()
if "qrCode" in data:
    b64 = data["qrCode"].split(",")[1]
    img = base64.b64decode(b64)
    with open("/tmp/whatsapp_qr_fresh.png", "wb") as f:
        f.write(img)
    print(f"6. QR saved: {len(img)} bytes")
else:
    # Try without parsing
    r6 = httpx.get(f"{settings.openwa_base_url}/sessions/{sid}/qr", headers=h, timeout=30)
    print(f"6. QR response: {r6.text[:200]}")

# 7. Print update info
print(f"\n=== ACTION REQUIRED ===")
print(f"New session ID: {sid}")
print(f"Update .env OPENWA_SESSION_ID={sid}")
print(f"Then run: docker compose up -d backend")
