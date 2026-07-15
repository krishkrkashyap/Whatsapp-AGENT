"""Start session and wait for ready."""
import sys; sys.path.insert(0, '/app')
import httpx, time, json
from app.config import settings

h = {"X-API-Key": settings.openwa_api_key, "Content-Type": "application/json"}
sid = settings.openwa_session_id

# Start session
r = httpx.post(f"{settings.openwa_base_url}/sessions/{sid}/start", headers=h, timeout=120)
print(f"Start: {r.status_code} {r.json().get('status','?')}")

# Wait for ready
for i in range(30):
    time.sleep(3)
    r2 = httpx.get(f"{settings.openwa_base_url}/sessions/{sid}", headers=h, timeout=15)
    status = r2.json().get("status","?")
    print(f"  {i*3}s: {status}")
    if status == "ready":
        print("READY!")
        # Register webhook
        r3 = httpx.post(f"{settings.openwa_base_url}/sessions/{sid}/webhooks", headers=h,
            json={"url": "http://backend:8000/webhook/whatsapp", "events": ["message.*"]}, timeout=15)
        print(f"Webhook: {r3.status_code}")
        break
