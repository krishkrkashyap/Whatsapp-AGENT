"""Check OpenWA messages for Ruchi's chat."""
import sys; sys.path.insert(0, '/app')
import httpx
from app.config import settings

h = {'X-API-Key': settings.openwa_api_key}
sid = settings.openwa_session_id

# Try to get messages
r = httpx.get(f'{settings.openwa_base_url}/sessions/{sid}/messages?limit=5', headers=h, timeout=30)
print(f'Messages endpoint: {r.status_code}')
try:
    data = r.json()
    if isinstance(data, list):
        msgs = data
    elif isinstance(data, dict):
        msgs = data.get('data', data.get('messages', []))
    else:
        msgs = []
    print(f'Count: {len(msgs)}')
    for m in msgs[:5]:
        print(f'  From: {m.get("from","?")} To: {m.get("to","?")} Body: {str(m.get("body","?"))[:100]}')
except Exception as e:
    print(f'Error: {e}')
    print(f'Raw: {r.text[:500]}')

# Try to get contacts
r2 = httpx.get(f'{settings.openwa_base_url}/sessions/{sid}/contacts', headers=h, timeout=30)
print(f'\nContacts: {r2.status_code}')
try:
    data2 = r2.json()
    if isinstance(data2, list):
        print(f'Count: {len(data2)}')
        for c in data2[:10]:
            print(f'  {c.get("id","?")} | {c.get("name","?")} | {c.get("number","?")}')
    else:
        print(f'Response: {str(data2)[:300]}')
except Exception as e:
    print(f'Error: {e}')
