# Smart Assistant P1 — Live-Ops Q&A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the bot answer questions about live operational data (tasks, SOPs, staff) via curated, permission-gated query tools chosen by the LLM — no LLM-generated SQL.

**Architecture:** A new `ops_tools` module exposes a registry of safe parametrized lookups, each enforcing its own permission rule. A new `assistant_service` picks one tool (Groq JSON mode, keyword fallback), runs it, and synthesizes a natural-language answer via the existing `nlu_service.ask(question, context, language)`. The webhook's blind `nlu.ask(body)` general-question branches are rewired to `assistant.answer(...)`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Postgres (prod) / SQLite (tests), pytest, Groq llama-3.3-70b via existing `NLUService`.

## Global Constraints

- Live data is queried from live tables only — never indexed/copied. (verbatim from spec)
- Curated query tools only; **no LLM-generated SQL.** (verbatim from spec)
- Permission enforced **inside each tool**: employee = own data only; admin = everything. (verbatim from spec)
- Every tool / LLM call wrapped so one failure degrades gracefully. (verbatim from spec)
- Preserve all existing webhook behavior when the assistant path returns nothing useful. (verbatim from spec)
- This plan covers **P1 only.** P2 (FTS docs), P3 (memory), P4 (NLU) are separate plans. `assistant_service.answer` is written so P2/P3 can extend it without rework.

## Test loop (no image rebuild needed per-iteration)

The backend image has no source mount. For fast iteration, copy changed files into the running container, then run pytest there:

```bash
# from repo root
docker cp backend/app/services/ops_tools.py crusty-backend:/app/app/services/ops_tools.py
docker cp backend/tests/test_ops_tools.py crusty-backend:/app/tests/test_ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -v
```

Final deploy at end of plan = `docker compose build backend && docker compose up -d backend`.

## File Structure

- Create: `backend/app/services/ops_tools.py` — tool functions + registry + dispatch.
- Create: `backend/app/services/assistant_service.py` — tool selection + answer orchestration.
- Create: `backend/tests/test_ops_tools.py` — tool + permission tests.
- Create: `backend/tests/test_assistant_service.py` — selection + orchestration tests (mock LLM).
- Modify: `backend/tests/conftest.py` — add `sop_definitions` table to the `db` fixture.
- Modify: `backend/app/routers/webhook.py` — rewire HELP/else branches to `assistant.answer`.

## Model reference (read-only, for implementers)

- `Employee`: `id, name, department, role, whatsapp_number, is_admin, is_active, preferred_language`.
- `Task`: `id, title, assigned_to_id, assigned_by_id, status (TaskStatus enum: pending/in_progress/done/blocked/escalated), priority (Priority enum: high/medium/low), due_date (nullable datetime), assigned_at`.
- `SOPDefinition`: `id, title, department, frequency (Frequency enum), start_time (str HH:MM), assigned_to_id, requires_attachment, status (SOPStatus enum: active/...)`.
- `TaskManager(db).get_pending_tasks(employee_id) -> list[Task]` (ordered), `.get_all_pending() -> list[Task]`.
- `EmployeeService(db).get_by_id(id)`, `.get_by_name_or_mention(text)`, `.get_all_admins()`.

---

### Task 1: Ops tools — self-scoped task lookups

**Files:**
- Create: `backend/app/services/ops_tools.py`
- Test: `backend/tests/test_ops_tools.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces: `my_pending_tasks(employee, db) -> str`, `my_tasks_today(employee, db) -> str`, `task_lookup(employee, db, query: str) -> str`. Each returns a short plain-text block (lines), or a "none" message. All self-scoped: only rows where `Task.assigned_to_id == employee.id`.

- [ ] **Step 1: Add `sop_definitions` to the test DB fixture**

In `backend/tests/conftest.py`, add the model import and the table so ops-tool tests can seed SOPs:

```python
# add near the other model imports
import app.models.sop  # noqa
```

In the `db` fixture's `tables=[...]` list, add:

```python
            Base.metadata.tables["sop_definitions"],
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_ops_tools.py`:

```python
from datetime import datetime, timezone, timedelta
from app.models.employee import Employee
from app.models.task import Task, Priority, TaskStatus
from app.services import ops_tools


def _emp(db, name="Krish", admin=False, dept="IT"):
    e = Employee(name=name, department=dept, role="Staff",
                 whatsapp_number=f"+9100000{len(name)}{int(admin)}", is_admin=admin)
    db.add(e); db.commit(); db.refresh(e)
    return e


def _task(db, owner_id, title, status=TaskStatus.pending, due=None):
    t = Task(title=title, priority=Priority.medium, status=status,
             assigned_by_id="admin1", assigned_to_id=owner_id,
             assigned_at=datetime.now(timezone.utc), due_date=due)
    db.add(t); db.commit(); db.refresh(t)
    return t


def test_my_pending_tasks_lists_only_own_open_tasks(db):
    me = _emp(db, "Krish")
    other = _emp(db, "Sandeep")
    _task(db, me.id, "Clean oven")
    _task(db, me.id, "Old task", status=TaskStatus.done)
    _task(db, other.id, "Not mine")
    out = ops_tools.my_pending_tasks(me, db)
    assert "Clean oven" in out
    assert "Old task" not in out      # done excluded
    assert "Not mine" not in out      # other employee excluded


def test_my_pending_tasks_empty(db):
    me = _emp(db, "Krish")
    assert "no pending" in ops_tools.my_pending_tasks(me, db).lower()


def test_task_lookup_matches_by_substring(db):
    me = _emp(db, "Krish")
    _task(db, me.id, "Send daily production report")
    out = ops_tools.task_lookup(me, db, query="production")
    assert "production report" in out.lower()
    assert "pending" in out.lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
docker cp backend/tests/conftest.py crusty-backend:/app/tests/conftest.py
docker cp backend/tests/test_ops_tools.py crusty-backend:/app/tests/test_ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ops_tools'`.

- [ ] **Step 4: Write minimal implementation**

Create `backend/app/services/ops_tools.py`:

```python
"""Curated, permission-gated read-only lookups for the smart assistant.

Each tool takes (employee, db, **args) and returns a SHORT plain-text block the
LLM will turn into a natural answer. Self-scoped tools only ever read the
caller's own rows; admin-only tools are gated in dispatch(). No tool builds SQL
from free text — queries are fixed and parametrized.
"""
import logging
from sqlalchemy import select
from app.models.task import Task, TaskStatus

logger = logging.getLogger("ops_tools")

_OPEN = (TaskStatus.pending, TaskStatus.in_progress)


def _fmt_task(t) -> str:
    due = f" (due {t.due_date.strftime('%d %b')})" if getattr(t, "due_date", None) else ""
    return f"- {t.title} [{t.priority.value}] {t.status.value}{due}"


def my_pending_tasks(employee, db) -> str:
    rows = db.execute(
        select(Task).where(Task.assigned_to_id == employee.id, Task.status.in_(_OPEN))
        .order_by(Task.priority, Task.assigned_at)
    ).scalars().all()
    if not rows:
        return f"{employee.name} has no pending tasks."
    return f"{employee.name}'s pending tasks:\n" + "\n".join(_fmt_task(t) for t in rows)


def my_tasks_today(employee, db) -> str:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    rows = db.execute(
        select(Task).where(Task.assigned_to_id == employee.id, Task.status.in_(_OPEN))
        .order_by(Task.assigned_at)
    ).scalars().all()
    todays = [t for t in rows if getattr(t, "due_date", None) and t.due_date.date() == today]
    pool = todays or rows
    if not pool:
        return f"{employee.name} has no tasks for today."
    label = "due today" if todays else "open (no date set)"
    return f"{employee.name}'s tasks {label}:\n" + "\n".join(_fmt_task(t) for t in pool)


def task_lookup(employee, db, query: str = "") -> str:
    q = (query or "").strip().lower()
    rows = db.execute(
        select(Task).where(Task.assigned_to_id == employee.id).order_by(Task.assigned_at.desc())
    ).scalars().all()
    if q:
        rows = [t for t in rows if q in t.title.lower()]
    if not rows:
        return f"No task matching '{query}' found for {employee.name}."
    return "\n".join(_fmt_task(t) for t in rows[:5])
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/ops_tools.py crusty-backend:/app/app/services/ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ops_tools.py backend/tests/test_ops_tools.py backend/tests/conftest.py
git commit -m "feat(assistant): self-scoped ops task tools"
```

---

### Task 2: Ops tools — SOP lookups

**Files:**
- Modify: `backend/app/services/ops_tools.py`
- Test: `backend/tests/test_ops_tools.py`

**Interfaces:**
- Produces: `who_owns_sop(employee, db, name: str) -> str`, `sop_schedule_today(employee, db, dept: str = "") -> str`. Both readable by any employee (SOP roster is not private). `who_owns_sop` matches SOP title by substring and names the assignee + start time.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ops_tools.py`:

```python
from app.models.sop import SOPDefinition, Frequency, SOPStatus


def _sop(db, title, owner_id, dept="Prahladnagar - Kitchen Section", start="09:00"):
    s = SOPDefinition(title=title, department=dept, frequency=Frequency.daily,
                      start_time=start, assigned_to_id=owner_id, status=SOPStatus.active)
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_who_owns_sop_names_assignee(db):
    me = _emp(db, "Krish")
    worker = _emp(db, "Narendra", dept="Prahladnagar - Kitchen Section")
    _sop(db, "Kitchen Floor Cleaning", worker.id, start="09:00")
    out = ops_tools.who_owns_sop(me, db, name="floor")
    assert "Narendra" in out
    assert "Kitchen Floor Cleaning" in out
    assert "09:00" in out


def test_who_owns_sop_not_found(db):
    me = _emp(db, "Krish")
    assert "no sop" in ops_tools.who_owns_sop(me, db, name="zzz").lower()


def test_sop_schedule_today_filters_by_dept(db):
    me = _emp(db, "Krish")
    w = _emp(db, "Narendra", dept="Prahladnagar - Kitchen Section")
    _sop(db, "Kitchen Opening", w.id, dept="Prahladnagar - Kitchen Section", start="09:00")
    _sop(db, "Shop Open", w.id, dept="Prahladnagar - Seating Area", start="08:20")
    out = ops_tools.sop_schedule_today(me, db, dept="Kitchen")
    assert "Kitchen Opening" in out
    assert "Shop Open" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker cp backend/tests/test_ops_tools.py crusty-backend:/app/tests/test_ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -k sop -v
```
Expected: FAIL with `AttributeError: module 'app.services.ops_tools' has no attribute 'who_owns_sop'`.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/ops_tools.py`:

```python
from app.models.sop import SOPDefinition, SOPStatus
from app.models.employee import Employee


def _emp_name(db, emp_id) -> str:
    e = db.get(Employee, emp_id)
    return e.name if e else "Unknown"


def who_owns_sop(employee, db, name: str = "") -> str:
    q = (name or "").strip().lower()
    rows = db.execute(
        select(SOPDefinition).where(SOPDefinition.status == SOPStatus.active)
    ).scalars().all()
    if q:
        rows = [s for s in rows if q in s.title.lower()]
    if not rows:
        return f"No SOP matching '{name}' found."
    out = []
    for s in rows[:5]:
        out.append(f"- {s.title} ({s.department}) → {_emp_name(db, s.assigned_to_id)} at {s.start_time}")
    return "\n".join(out)


def sop_schedule_today(employee, db, dept: str = "") -> str:
    d = (dept or "").strip().lower()
    rows = db.execute(
        select(SOPDefinition).where(SOPDefinition.status == SOPStatus.active)
        .order_by(SOPDefinition.start_time)
    ).scalars().all()
    if d:
        rows = [s for s in rows if d in s.department.lower()]
    if not rows:
        return "No active SOPs found" + (f" for '{dept}'." if dept else ".")
    return "Today's SOP schedule:\n" + "\n".join(
        f"- {s.start_time} {s.title} → {_emp_name(db, s.assigned_to_id)}" for s in rows[:20])
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/ops_tools.py crusty-backend:/app/app/services/ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -v
```
Expected: all passed (6 total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ops_tools.py backend/tests/test_ops_tools.py
git commit -m "feat(assistant): SOP roster ops tools"
```

---

### Task 3: Ops tools — admin-only lookups

**Files:**
- Modify: `backend/app/services/ops_tools.py`
- Test: `backend/tests/test_ops_tools.py`

**Interfaces:**
- Produces: `dept_pending_count(employee, db, dept: str = "") -> str`, `overdue_tasks(employee, db, dept: str = "") -> str`, `team_status(employee, db) -> str`, `staff_lookup(employee, db, name: str) -> str`. These read across all employees; gating happens in Task 4's `dispatch`, so the functions themselves assume the caller is allowed.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ops_tools.py`:

```python
def test_team_status_lists_all_open_tasks(db):
    admin = _emp(db, "Aditya", admin=True)
    a = _emp(db, "Krish")
    b = _emp(db, "Sandeep")
    _task(db, a.id, "Task A")
    _task(db, b.id, "Task B")
    out = ops_tools.team_status(admin, db)
    assert "Task A" in out and "Task B" in out
    assert "Krish" in out and "Sandeep" in out


def test_overdue_tasks_lists_past_due(db):
    admin = _emp(db, "Aditya", admin=True)
    a = _emp(db, "Krish")
    past = datetime.now(timezone.utc) - timedelta(days=2)
    _task(db, a.id, "Late task", due=past)
    _task(db, a.id, "Future task", due=datetime.now(timezone.utc) + timedelta(days=2))
    out = ops_tools.overdue_tasks(admin, db)
    assert "Late task" in out
    assert "Future task" not in out


def test_staff_lookup_returns_role_dept(db):
    admin = _emp(db, "Aditya", admin=True)
    _emp(db, "Narendra", dept="Prahladnagar - Kitchen Section")
    out = ops_tools.staff_lookup(admin, db, name="Narendra")
    assert "Narendra" in out
    assert "Kitchen Section" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker cp backend/tests/test_ops_tools.py crusty-backend:/app/tests/test_ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -k "team or overdue or staff" -v
```
Expected: FAIL with `AttributeError: ... has no attribute 'team_status'`.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/ops_tools.py`:

```python
def team_status(employee, db) -> str:
    rows = db.execute(
        select(Task).where(Task.status.in_(_OPEN)).order_by(Task.assigned_to_id)
    ).scalars().all()
    if not rows:
        return "No pending tasks across the team."
    out = ["Team pending tasks:"]
    for t in rows[:30]:
        out.append(f"- {t.title} → {_emp_name(db, t.assigned_to_id)} [{t.priority.value}]")
    return "\n".join(out)


def dept_pending_count(employee, db, dept: str = "") -> str:
    rows = db.execute(select(Task).where(Task.status.in_(_OPEN))).scalars().all()
    counts = {}
    for t in rows:
        e = db.get(Employee, t.assigned_to_id)
        d = e.department if e else "Unknown"
        counts[d] = counts.get(d, 0) + 1
    if dept:
        dl = dept.strip().lower()
        counts = {k: v for k, v in counts.items() if dl in k.lower()}
    if not counts:
        return "No pending tasks" + (f" in '{dept}'." if dept else ".")
    return "Pending by department:\n" + "\n".join(f"- {k}: {v}" for k, v in sorted(counts.items()))


def overdue_tasks(employee, db, dept: str = "") -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    rows = db.execute(select(Task).where(Task.status.in_(_OPEN))).scalars().all()
    overdue = []
    for t in rows:
        if not getattr(t, "due_date", None):
            continue
        due = t.due_date if t.due_date.tzinfo else t.due_date.replace(tzinfo=timezone.utc)
        if due < now:
            e = db.get(Employee, t.assigned_to_id)
            if dept and dept.strip().lower() not in (e.department.lower() if e else ""):
                continue
            overdue.append((t, e))
    if not overdue:
        return "No overdue tasks."
    return "Overdue tasks:\n" + "\n".join(
        f"- {t.title} → {(e.name if e else 'Unknown')} (due {t.due_date.strftime('%d %b')})"
        for t, e in overdue[:20])


def staff_lookup(employee, db, name: str = "") -> str:
    q = (name or "").strip().lower()
    rows = db.execute(select(Employee)).scalars().all()
    rows = [e for e in rows if q in e.name.lower()] if q else rows
    if not rows:
        return f"No staff matching '{name}'."
    return "\n".join(f"- {e.name} — {e.role} · {e.department} · {e.whatsapp_number}" for e in rows[:10])
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/ops_tools.py crusty-backend:/app/app/services/ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -v
```
Expected: all passed (9 total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ops_tools.py backend/tests/test_ops_tools.py
git commit -m "feat(assistant): admin-only ops tools (team/overdue/dept/staff)"
```

---

### Task 4: Tool registry + permission-gated dispatch

**Files:**
- Modify: `backend/app/services/ops_tools.py`
- Test: `backend/tests/test_ops_tools.py`

**Interfaces:**
- Produces:
  - `TOOL_REGISTRY: dict[str, dict]` — maps tool name → `{"fn": callable, "admin_only": bool, "args": list[str], "desc": str}`.
  - `tool_catalog() -> str` — newline list of `name(args) — desc` for the LLM prompt.
  - `dispatch(tool_name: str, args: dict, employee, db) -> str` — returns the tool output, a polite refusal if `admin_only` and `not employee.is_admin`, `""` for an unknown tool, and a graceful message on exception.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ops_tools.py`:

```python
def test_dispatch_self_tool_runs(db):
    me = _emp(db, "Krish")
    _task(db, me.id, "Clean oven")
    out = ops_tools.dispatch("my_pending_tasks", {}, me, db)
    assert "Clean oven" in out


def test_dispatch_admin_tool_blocked_for_employee(db):
    me = _emp(db, "Krish")  # not admin
    out = ops_tools.dispatch("team_status", {}, me, db)
    assert "only" in out.lower() or "admin" in out.lower()


def test_dispatch_admin_tool_allowed_for_admin(db):
    admin = _emp(db, "Aditya", admin=True)
    a = _emp(db, "Krish")
    _task(db, a.id, "Task A")
    out = ops_tools.dispatch("team_status", {}, admin, db)
    assert "Task A" in out


def test_dispatch_unknown_tool_returns_empty(db):
    me = _emp(db, "Krish")
    assert ops_tools.dispatch("no_such_tool", {}, me, db) == ""


def test_dispatch_passes_args(db):
    me = _emp(db, "Krish")
    _task(db, me.id, "Send production report")
    out = ops_tools.dispatch("task_lookup", {"query": "production"}, me, db)
    assert "production" in out.lower()


def test_tool_catalog_lists_tools():
    cat = ops_tools.tool_catalog()
    assert "my_pending_tasks" in cat and "team_status" in cat
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker cp backend/tests/test_ops_tools.py crusty-backend:/app/tests/test_ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -k dispatch -v
```
Expected: FAIL with `AttributeError: ... has no attribute 'dispatch'`.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/ops_tools.py`:

```python
TOOL_REGISTRY = {
    "my_pending_tasks": {"fn": my_pending_tasks, "admin_only": False, "args": [],
                          "desc": "the caller's own open tasks"},
    "my_tasks_today": {"fn": my_tasks_today, "admin_only": False, "args": [],
                        "desc": "the caller's tasks due today"},
    "task_lookup": {"fn": task_lookup, "admin_only": False, "args": ["query"],
                     "desc": "status of the caller's task matching a keyword"},
    "who_owns_sop": {"fn": who_owns_sop, "admin_only": False, "args": ["name"],
                      "desc": "which staff member owns an SOP and when it runs"},
    "sop_schedule_today": {"fn": sop_schedule_today, "admin_only": False, "args": ["dept"],
                            "desc": "today's SOP schedule, optionally filtered by department"},
    "dept_pending_count": {"fn": dept_pending_count, "admin_only": True, "args": ["dept"],
                            "desc": "count of open tasks per department"},
    "overdue_tasks": {"fn": overdue_tasks, "admin_only": True, "args": ["dept"],
                       "desc": "all past-due open tasks"},
    "team_status": {"fn": team_status, "admin_only": True, "args": [],
                     "desc": "every open task across the whole team"},
    "staff_lookup": {"fn": staff_lookup, "admin_only": True, "args": ["name"],
                      "desc": "a staff member's role, department and contact"},
}


def tool_catalog() -> str:
    lines = []
    for name, meta in TOOL_REGISTRY.items():
        args = ", ".join(meta["args"]) or "none"
        scope = " [admin]" if meta["admin_only"] else ""
        lines.append(f"{name}(args: {args}){scope} — {meta['desc']}")
    return "\n".join(lines)


def dispatch(tool_name: str, args: dict, employee, db) -> str:
    meta = TOOL_REGISTRY.get(tool_name)
    if not meta:
        return ""
    if meta["admin_only"] and not employee.is_admin:
        return "Sorry, only an admin can ask that."
    allowed = {k: v for k, v in (args or {}).items() if k in meta["args"]}
    try:
        return meta["fn"](employee, db, **allowed)
    except Exception as e:
        logger.warning("ops tool %s failed: %s", tool_name, e)
        return "Couldn't fetch that right now."
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/ops_tools.py crusty-backend:/app/app/services/ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_ops_tools.py -v
```
Expected: all passed (15 total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ops_tools.py backend/tests/test_ops_tools.py
git commit -m "feat(assistant): tool registry + permission-gated dispatch"
```

---

### Task 5: Assistant — tool selection (LLM + keyword fallback)

**Files:**
- Create: `backend/app/services/assistant_service.py`
- Test: `backend/tests/test_assistant_service.py`

**Interfaces:**
- Consumes: `ops_tools.tool_catalog()`, `ops_tools.TOOL_REGISTRY`, `nlu_service._call_llm(prompt, json_mode=True)`.
- Produces: `select_tool(question: str, employee) -> tuple[str | None, dict]`. Returns `(tool_name, args)` or `(None, {})` when nothing fits. Tries the LLM (JSON mode) first; on any failure or invalid tool name, falls back to keyword routing.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_assistant_service.py`:

```python
import types
from app.services import assistant_service as asv


class _Emp:
    def __init__(self, admin=False):
        self.id = "e1"; self.name = "Krish"; self.is_admin = admin


def test_select_tool_uses_llm(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "x")
    monkeypatch.setattr(asv.nlu_service, "_call_llm",
                        lambda prompt, json_mode=False: '{"tool":"my_pending_tasks","args":{}}')
    name, args = asv.select_tool("what are my tasks", _Emp())
    assert name == "my_pending_tasks"


def test_select_tool_invalid_llm_falls_back_to_keyword(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "x")
    monkeypatch.setattr(asv.nlu_service, "_call_llm",
                        lambda prompt, json_mode=False: '{"tool":"garbage","args":{}}')
    name, _ = asv.select_tool("my pending tasks", _Emp())
    assert name == "my_pending_tasks"   # keyword fallback recovered it


def test_select_tool_keyword_when_no_api_key(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    name, _ = asv.select_tool("show team status", _Emp(admin=True))
    assert name == "team_status"


def test_select_tool_none_for_unrelated(monkeypatch):
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    name, _ = asv.select_tool("what is the capital of France", _Emp())
    assert name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker cp backend/tests/test_assistant_service.py crusty-backend:/app/tests/test_assistant_service.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_assistant_service.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.assistant_service'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/assistant_service.py`:

```python
"""Smart assistant — answers general questions from live ops data.

P1: pick one curated ops tool (LLM JSON mode, keyword fallback), run it, and let
the existing nlu_service.ask synthesize a natural answer. Doc search (P2) and
conversation memory (P3) extend answer() later without changing this contract.
"""
import json
import logging
from app.services import ops_tools
from app.services.nlu import nlu_service

logger = logging.getLogger("assistant")

# Keyword fallback routing — (substrings, tool_name). First match wins.
_KEYWORD_ROUTES = [
    (["team status", "team pending", "sabka", "everyone", "all tasks"], "team_status"),
    (["overdue", "late task", "past due"], "overdue_tasks"),
    (["how many", "count", "department pending", "dept pending"], "dept_pending_count"),
    (["who owns", "who does", "who handles", "owner of", "kaun karta"], "who_owns_sop"),
    (["schedule", "today's sop", "sop today", "roster"], "sop_schedule_today"),
    (["my task", "my pending", "mera task", "mere task", "pending"], "my_pending_tasks"),
    (["today", "aaj"], "my_tasks_today"),
    (["who is", "contact of", "phone of", "role of", "staff"], "staff_lookup"),
]


def _keyword_route(question: str):
    q = question.lower()
    for needles, tool in _KEYWORD_ROUTES:
        if any(n in q for n in needles):
            return tool, {}
    return None, {}


def select_tool(question: str, employee):
    """Return (tool_name|None, args). LLM first, keyword fallback."""
    if nlu_service.api_key:
        prompt = (
            "You route an internal task-bot question to ONE lookup tool, or none.\n"
            f"Tools:\n{ops_tools.tool_catalog()}\n\n"
            f"Question: \"{question}\"\n\n"
            'Respond JSON ONLY: {"tool": "<name or null>", "args": {<arg: value>}}. '
            "Use null when no tool fits (general chit-chat / world knowledge)."
        )
        try:
            raw = nlu_service._call_llm(prompt, json_mode=True)
            data = json.loads(raw)
            tool = data.get("tool")
            args = data.get("args") or {}
            if tool in ops_tools.TOOL_REGISTRY:
                return tool, (args if isinstance(args, dict) else {})
            if tool in (None, "null", ""):
                # LLM explicitly said "no tool" — trust it, but let keyword have a
                # last word so obvious phrasings still route.
                return _keyword_route(question)
        except Exception as e:
            logger.warning("tool selection LLM failed: %s", e)
    return _keyword_route(question)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/assistant_service.py crusty-backend:/app/app/services/assistant_service.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_assistant_service.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/assistant_service.py backend/tests/test_assistant_service.py
git commit -m "feat(assistant): tool selection with LLM + keyword fallback"
```

---

### Task 6: Assistant — answer() orchestration

**Files:**
- Modify: `backend/app/services/assistant_service.py`
- Test: `backend/tests/test_assistant_service.py`

**Interfaces:**
- Consumes: `select_tool`, `ops_tools.dispatch`, `nlu_service.ask(question, context, language)`.
- Produces: `answer(question: str, employee, db, language: str = "english") -> str`. Selects+runs a tool; if it yields ops context, synthesizes with that context; otherwise falls back to a plain `nlu_service.ask`. Never raises.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_assistant_service.py`:

```python
def test_answer_uses_ops_context(monkeypatch, db):
    from app.models.employee import Employee
    from app.models.task import Task, Priority, TaskStatus
    from datetime import datetime, timezone
    e = Employee(name="Krish", department="IT", role="Staff",
                 whatsapp_number="+910001", is_admin=False)
    db.add(e); db.commit(); db.refresh(e)
    db.add(Task(title="Clean oven", priority=Priority.medium, status=TaskStatus.pending,
                assigned_by_id="a", assigned_to_id=e.id,
                assigned_at=datetime.now(timezone.utc))); db.commit()

    captured = {}
    def fake_ask(question, context="", language="english"):
        captured["context"] = context
        return "ANSWER"
    monkeypatch.setattr(asv.nlu_service, "api_key", "")  # force keyword route
    monkeypatch.setattr(asv.nlu_service, "ask", fake_ask)

    out = asv.answer("what are my pending tasks", e, db, language="english")
    assert out == "ANSWER"
    assert "Clean oven" in captured["context"]   # ops result was passed as context


def test_answer_falls_back_without_tool(monkeypatch, db):
    from app.models.employee import Employee
    e = Employee(name="Krish", department="IT", role="Staff",
                 whatsapp_number="+910002", is_admin=False)
    db.add(e); db.commit(); db.refresh(e)
    monkeypatch.setattr(asv.nlu_service, "api_key", "")
    monkeypatch.setattr(asv.nlu_service, "ask",
                        lambda question, context="", language="english": "GENERAL")
    out = asv.answer("what is the capital of France", e, db)
    assert out == "GENERAL"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
docker cp backend/tests/test_assistant_service.py crusty-backend:/app/tests/test_assistant_service.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_assistant_service.py -k answer -v
```
Expected: FAIL with `AttributeError: module ... has no attribute 'answer'`.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/assistant_service.py`:

```python
def answer(question: str, employee, db, language: str = "english") -> str:
    """Answer a general question using live ops data when a tool fits, else a
    plain LLM answer. Never raises — always returns a string."""
    ops_context = ""
    try:
        tool, args = select_tool(question, employee)
        if tool:
            ops_context = ops_tools.dispatch(tool, args, employee, db)
    except Exception as e:
        logger.warning("assistant tool phase failed: %s", e)

    try:
        if ops_context:
            return nlu_service.ask(question, context=ops_context, language=language)
        return nlu_service.ask(question, language=language)
    except Exception as e:
        logger.warning("assistant synthesize failed: %s", e)
        return ops_context or "Sorry, I couldn't process that right now."
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker cp backend/app/services/assistant_service.py crusty-backend:/app/app/services/assistant_service.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/test_assistant_service.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/assistant_service.py backend/tests/test_assistant_service.py
git commit -m "feat(assistant): answer() orchestration over ops tools"
```

---

### Task 7: Wire the webhook general-question branches to the assistant

**Files:**
- Modify: `backend/app/routers/webhook.py` (the `intent == "HELP"` else-branch and the final `else` branch — the two places that currently call `nlu_service.ask(body, language=lang)`)

**Interfaces:**
- Consumes: `assistant_service.answer(question, employee, db, language)`.
- Produces: no new symbol; replaces two `nlu_service.ask` call sites.

- [ ] **Step 1: Add the import**

At the top of `backend/app/routers/webhook.py`, near the other service imports (e.g. after `from app.services.nlu import nlu_service`), add:

```python
from app.services.assistant_service import answer as assistant_answer
```

- [ ] **Step 2: Replace the HELP-branch general answer**

Find (around the `elif intent == "HELP":` block):

```python
            else:
                answer = nlu_service.ask(body, language=lang)
                send_whatsapp(employee.whatsapp_number, answer)
```

Replace with:

```python
            else:
                reply = assistant_answer(body, employee, db, language=lang)
                send_whatsapp(employee.whatsapp_number, reply)
```

- [ ] **Step 3: Replace the final else-branch general answer**

Find the final `else:` block of the intent dispatch:

```python
        else:
            answer = nlu_service.ask(body, language=lang)
            send_whatsapp(employee.whatsapp_number, answer)
```

Replace with:

```python
        else:
            reply = assistant_answer(body, employee, db, language=lang)
            send_whatsapp(employee.whatsapp_number, reply)
```

- [ ] **Step 4: Verify the module imports cleanly + full test suite**

Run:
```bash
docker cp backend/app/routers/webhook.py crusty-backend:/app/app/routers/webhook.py
docker cp backend/app/services/assistant_service.py crusty-backend:/app/app/services/assistant_service.py
docker cp backend/app/services/ops_tools.py crusty-backend:/app/app/services/ops_tools.py
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend python -c "from app.routers import webhook; print('import OK')"
MSYS_NO_PATHCONV=1 docker exec -w /app crusty-backend pytest tests/ -v
```
Expected: `import OK` and the full suite passes (existing attachment/checklist tests + the new 21 assistant/ops tests).

- [ ] **Step 5: Build, deploy, smoke-test live**

Run:
```bash
docker compose build backend && docker compose up -d backend
sleep 6
```
Then from Krish's WhatsApp (an admin), send: `what are my pending tasks` → expect a real list. Send `team status` → expect the team list. Send `who handles kitchen floor cleaning` → expect Narendra. Confirm a non-admin asking `team status` gets the polite refusal.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/webhook.py
git commit -m "feat(assistant): route general questions through live-ops assistant"
```

---

## Self-Review

**Spec coverage (P1 scope):**
- Ops tools (self + SOP + admin) — Tasks 1–3. ✓
- Permission gating inside dispatch — Task 4 + tests. ✓
- Curated tools, no LLM-SQL — registry/dispatch only call fixed fns. ✓
- LLM tool selection + keyword fallback — Task 5. ✓
- Orchestrated answer, graceful fallback, never raises — Task 6. ✓
- Webhook wiring preserving existing behavior when no tool fits — Task 7 (falls back to `nlu_service.ask`). ✓
- Live data from live tables (not indexed) — all tools query tables directly. ✓
- (Deferred to later plans: P2 FTS docs, P3 memory, P4 NLU — explicitly out of this plan.)

**Placeholder scan:** No TBD/TODO; every code step has complete code. ✓

**Type consistency:** `dispatch(tool_name, args, employee, db)`, `select_tool(question, employee) -> (name, args)`, `answer(question, employee, db, language)` used consistently across tasks 4–7. Tool fns all `(employee, db, **args) -> str`. ✓
