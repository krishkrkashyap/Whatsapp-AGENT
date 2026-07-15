"""Quick check."""
import sys, json; sys.path.insert(0, '/app')
import httpx
from app.config import settings

sid = settings.openwa_session_id
h = {"X-API-Key": settings.openwa_api_key}

# Try contacts
try:
    r = httpx.get(f"{settings.openwa_base_url}/sessions/{sid}/contacts", headers=h, timeout=15)
    print(f"Contacts: {r.status_code}")
    j = r.json()
    if isinstance(j, list):
        print(f"Count: {len(j)}")
        for c in j[:5]:
            cid = c.get("id","?")
            cn = c.get("name","?")
            print(f"  {cid} | {cn}")
    else:
        print(json.dumps(j, indent=2)[:500])
except Exception as e:
    print(f"Contacts error: {e}")

# Try messages
try:
    r2 = httpx.get(f"{settings.openwa_base_url}/sessions/{sid}/messages", headers=h, timeout=15)
    print(f"\nMessages: {r2.status_code}")
    d2 = r2.json()
    print(f"Type: {type(d2).__name__}")
    if isinstance(d2, list):
        print(f"Count: {len(d2)}")
        for m in d2[:3]:
            print(f"  from={m.get('from','?')} body={str(m.get('body','?'))[:60]}")
    elif isinstance(d2, dict):
        print(json.dumps(d2, indent=2)[:500])
except Exception as e:
    print(f"Messages error: {e}")
