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


from app.models.sop import SOPDefinition, SOPStatus
from app.models.employee import Employee


def _emp_name(db, emp_id) -> str:
    e = db.get(Employee, emp_id)
    return e.name if e else "Unknown"


def who_owns_sop(employee, db, name: str = "") -> str:
    q = (name or "").strip().lower()
    rows = db.execute(
        select(SOPDefinition).where(SOPDefinition.status == SOPStatus.active)
        .order_by(SOPDefinition.start_time)
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
    return "Active SOP schedule:\n" + "\n".join(
        f"- {s.start_time} {s.title} → {_emp_name(db, s.assigned_to_id)}" for s in rows[:20])


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
                            "desc": "active SOP schedule, optionally filtered by department"},
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
