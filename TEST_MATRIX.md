# Test Matrix — WhatsApp Agent

## Environment
- Session: `<session-id>`
- Admin: `+91XXXXXXXXXX`
- Employees: `+91XXXXXXXXXX`, `+91XXXXXXXXXX`
- Bot: `+91XXXXXXXXXX`

---

## 1. Admin Commands (Krish)

| # | Test | Input | Expected Reply | Status |
|---|------|-------|----------------|--------|
| 1.1 | Help | `help` | Admin command list with all features | |
| 1.2 | Assign task with @mention | `@Ruchi Fix login page CSS by Friday high priority` | ✅ Task assigned to Ruchi | |
| 1.3 | Assign task without @mention | `assign to Raj deploy the server` | ✅ Task assigned to Raj | |
| 1.4 | Assign task with due date | `@Ruchi Complete report by Monday` | ✅ Task assigned with due date | |
| 1.5 | Invalid @mention | `@Nobody do this task` | ❌ 'Nobody' nahi mila | |
| 1.6 | Assign without target | `do this task` | ⚠️ Kisko assign karna hai? | |
| 1.7 | View all pending | `all tasks` | 📋 Team Pending Tasks list | |
| 1.8 | Follow up | `follow up` | 📋 All Pending Tasks list | |
| 1.9 | Team status | `sabka status` | 📋 Team Pending Tasks list | |
| 1.10 | URL fetch | `https://example.com what is this` | 🔍 Web Fetch Result | |
| 1.11 | Internal URL (SSRF test) | `http://localhost:8000/` | ❌ Internal URLs not allowed | |
| 1.12 | Cloud metadata (SSRF test) | `http://169.254.169.254/latest/` | ❌ Internal URLs not allowed | |
| 1.13 | General question | `what's the weather today?` | AI response (LLM) | |

## 2. Employee Commands (Ruchi / Raj)

| # | Test | Input | Expected Reply | Status |
|---|------|-------|----------------|--------|
| 2.1 | Help | `help` | Employee command list | |
| 2.2 | My tasks | `my tasks` | 📋 pending tasks list | |
| 2.3 | My tasks (Hindi) | `kya karna hai` | 📋 pending tasks list | |
| 2.4 | My tasks (alternate) | `pending` | 📋 pending tasks list | |
| 2.5 | Mark done | `done` | ✅ Task marked done | |
| 2.6 | Mark done (Hindi) | `ho gaya` | ✅ Task marked done | |
| 2.7 | Mark specific #2 | `done 2` | ✅ Task #2 marked done | |
| 2.8 | Multiple pending, no number | `done` | 📋 list + ask which number | |
| 2.9 | Trouble/Help | `stuck on this task` | 🔍 Solution found OR 🆘 escalated | |
| 2.10 | Problem (Hindi) | `samajh nahi aaya` | 🔍 Solution found OR 🆘 escalated | |
| 2.11 | Escalate | `escalate` | ❌ Main admin ko notify... | |
| 2.12 | Follow up own | `follow up` | 📋 own pending tasks | |
| 2.13 | Status own | `status` | 📋 own pending tasks | |
| 2.14 | Already registered | `register` | ✅ Aap pehle se registered hain! | |
| 2.15 | General question | `what is my task list?` | AI response | |

## 3. Unregistered User

| # | Test | Input | Expected Reply | Status |
|---|------|-------|----------------|--------|
| 3.1 | No reply (empty) | (empty body) | `{"status": "empty"}` | ✅ API-level |
| 3.2 | Register | `register my name is Test User` | ✅ Registration request submitted | |
| 3.3 | Already pending | `register my name is Test User2` | ⏳ Aapka request already pending | |
| 3.4 | Unregistered message | `hello` | ❌ Aap hamare system mein registered nahi hain | |
| 3.5 | URL from unregistered | `check http://evil.com` | ❌ Aap hamare system... (NOT webfetch) | |

## 4. Auth / Security Tests

| # | Test | Method | Expected | Status |
|---|------|--------|----------|--------|
| 4.1 | GET /api/employees/ (no auth) | curl | Returns names, NO phone numbers | |
| 4.2 | GET /api/employees/all (no auth) | curl | 401 Unauthorized | |
| 4.3 | POST /api/employees/ (no auth) | curl | 401 Unauthorized | |
| 4.4 | GET /api/tasks/ (no auth) | curl | Returns task list (no auth) | ⚠️ Known issue |
| 4.5 | GET /api/tasks/export (no auth) | curl | Returns CSV | ⚠️ Known issue |
| 4.6 | POST /api/auth/login wrong pass | curl | 401 | |
| 4.7 | POST /api/auth/login correct | curl | JWT token | |
| 4.8 | POST /api/openwa/setup-session (no auth) | curl | Creates session (no auth) | ⚠️ Known issue |
| 4.9 | Webhook POST (no auth) | curl | 200 OK (by design) | |
| 4.10 | Internal URL fetch SSRF | webhook with URL | Blocked | |

## 5. API Endpoint Tests (can run from terminal)

| # | Test | Command | Expected | Status |
|---|------|---------|----------|--------|
| 5.1 | Session status | `GET /api/openwa/session-status` | `{"status":"ready"}` | |
| 5.2 | Employee count | `GET /api/employees/count` | `{"count": 3}` | |
| 5.3 | Departments | `GET /api/employees/departments` | list of departments | |
| 5.4 | Tasks list | `GET /api/tasks/` | task list | |
| 5.5 | Pending tasks | `GET /api/tasks/pending` | pending tasks | |
| 5.6 | Pending count | `GET /api/tasks/count` | count | |
| 5.7 | Analytics overview | `GET /api/analytics/overview` | stats | |
| 5.8 | Simulate webhook | `POST /webhook/whatsapp` JSON | `{"status":"ok"}` | |

---

## Test Execution Log

Run each test, record result below.
