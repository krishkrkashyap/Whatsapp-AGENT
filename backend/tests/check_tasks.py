"""Check tasks, follow-ups via API."""
import httpx, json

BASE = "http://localhost:8000"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTc4MDYzOTIyNSwiaWF0IjoxNzgwNTUyODI1fQ.VzbjRPL3v3sDlDTjCf5xf4wb9OXMHiFxGv5jFyohA1E"
H = {"Authorization": f"Bearer {TOKEN}"}

# Tasks
r = httpx.get(f"{BASE}/api/tasks/", headers=H, timeout=15)
data = r.json()
if isinstance(data, list):
    print(f"=== TASKS ({len(data)}) ===")
    for t in data:
        tid = t.get("id", "?")[:8]
        title = t.get("title", "?")
        status = t.get("status", "?")
        prio = t.get("priority", "?")
        assign = t.get("assigned_to", "?")[:8] if t.get("assigned_to") else "unassigned"
        follow = t.get("follow_up_interval_hours", "none")
        print(f"  {tid} | {title} | {status} | {prio} | {assign} | followup={follow}")
else:
    print(f"Tasks response: {json.dumps(data, indent=2)[:1000]}")

# Count
r2 = httpx.get(f"{BASE}/api/tasks/count", headers=H, timeout=15)
print(f"\nCount: {r2.text}")

# Pending
r3 = httpx.get(f"{BASE}/api/tasks/pending", headers=H, timeout=15)
pdata = r3.json()
if isinstance(pdata, list):
    print(f"\n=== PENDING ({len(pdata)}) ===")
    for t in pdata:
        print(f"  {t.get('id','?')[:8]} | {t.get('title','?')} | assignee={t.get('assigned_to','?')[:8]}")
else:
    print(f"\nPending: {json.dumps(pdata, indent=2)[:500]}")

# KB languages
r4 = httpx.get(f"{BASE}/api/kb/languages", headers=H, timeout=15)
print(f"\nKB Languages: {r4.text}")

# Analytics
r5 = httpx.get(f"{BASE}/api/analytics/overview", headers=H, timeout=15)
print(f"\nAnalytics: {r5.text[:500]}")

# Conversations log
r6 = httpx.get(f"{BASE}/api/logs/conversations", headers=H, timeout=15)
cdata = r6.json()
if isinstance(cdata, list):
    print(f"\n=== CONVERSATIONS ({len(cdata)}) ===")
    for c in cdata[:5]:
        body = c.get("message_body", c.get("body", "?"))
        print(f"  {c.get('direction','?')} | {body[:60]}")
else:
    print(f"\nConversations: {json.dumps(cdata, indent=2)[:500]}")
