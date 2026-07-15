"""Check webhook registration."""
import sys; sys.path.insert(0, '/app')
import httpx
from app.config import settings

sid = settings.openwa_session_id
h = {"X-API-Key": settings.openwa_api_key, "Content-Type": "application/json"}

# Check existing webhooks
r = httpx.get(f"{settings.openwa_base_url}/sessions/{sid}/webhooks", headers=h, timeout=15)
whs = r.json()
print(f"Webhooks count: {len(whs) if isinstance(whs, list) else 0}")
for w in (whs if isinstance(whs, list) else []):
    wid = w.get("id","?")
    wurl = w.get("url","?")
    wev = w.get("events",[])
    wact = w.get("active","?")
    print(f"  ID: {wid} URL: {wurl} Events: {wev} Active: {wact}")
