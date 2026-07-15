"""Fresh OpenWA session setup."""
import sys; sys.path.insert(0, '/app')
import httpx, json, time, base64, os
from app.config import settings

h = {"X-API-Key": settings.openwa_api_key, "Content-Type": "application/json"}
base = settings.openwa_base_url

# 1. Check OpenWA health
r = httpx.get(f"{base}/health", headers=h, timeout=10)
print(f"1. OpenWA health: {r.status_code} {r.json().get('status','?')}")

# 2. List existing sessions
r2 = httpx.get(f"{base}/sessions", headers=h, timeout=10)
existing = r2.json()
print(f"2. Existing sessions: {len(existing) if isinstance(existing, list) else 'error'}")
for s in (existing if isinstance(existing, list) else []):
    print(f"   {s['id']} | {s['name']} | {s['status']}")

# 3. Create new session
r3 = httpx.post(f"{base}/sessions", headers=h, json={"name": "wabot"}, timeout=15)
print(f"3. Create: {r3.status_code}")
print(f"   Response: {r3.text[:300]}")
data = r3.json()
sid = data.get("id")
if not sid:
    print("ERROR: No session ID returned!")
    exit(1)
print(f"   Session ID: {sid}")

# 4. Start session
r4 = httpx.post(f"{base}/sessions/{sid}/start", headers=h, timeout=120)
print(f"4. Start: {r4.status_code} {r4.json().get('status','?')}")

# 5. Register webhook
r5 = httpx.post(f"{base}/sessions/{sid}/webhooks", headers=h,
    json={"url": "http://backend:8000/webhook/whatsapp", "events": ["message.*"]}, timeout=15)
print(f"5. Webhook: {r5.status_code} active={r5.json().get('active','?') if r5.status_code < 300 else '?'}")

# 6. Wait then get QR
print("6. Waiting for QR generation...")
time.sleep(12)
r6 = httpx.get(f"{base}/sessions/{sid}/qr", headers=h, timeout=30)
print(f"   QR status: {r6.status_code}")
resp6 = r6.json()
if "qrCode" in resp6:
    b64 = resp6["qrCode"].split(",")[1]
    img = base64.b64decode(b64)
    path = "/tmp/whatsapp_qr_fresh.png"
    with open(path, "wb") as f:
        f.write(img)
    print(f"   QR saved: {len(img)} bytes")
else:
    print(f"   Response: {r6.text[:300]}")

# 7. Print update info
print(f"\n=== DONE ===")
print(f"New session ID: {sid}")
print(f"Update .env: OPENWA_SESSION_ID={sid}")
