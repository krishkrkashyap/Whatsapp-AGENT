"""F-8: Analytics router — task completion rates, department stats, trends."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, case
from app.database import get_db
from app.models.task import Task, TaskStatus
from app.models.employee import Employee
from app.models.conversation import ConversationLog
from app.models.escalation import EscalationTicket
from app.routers.auth import verify_token

router = APIRouter()


@router.get("/report.xlsx")
def export_report(start: str = None, end: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """Download the date-ranged performance report as xlsx."""
    from app.services.analytics_report import build_report_xlsx
    buf, fname = build_report_xlsx(db, start, end)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

def _bounds(start: str = None, end: str = None):
    """Parse YYYY-MM-DD start/end into UTC datetime bounds (None if absent)."""
    from datetime import date
    s = datetime.combine(date.fromisoformat(start), datetime.min.time(), tzinfo=timezone.utc) if start else None
    e = datetime.combine(date.fromisoformat(end), datetime.max.time(), tzinfo=timezone.utc) if end else None
    return s, e


@router.get("/overview")
def analytics_overview(start: str = None, end: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """Get overall system analytics, optionally scoped to a [start,end] date range."""
    s, e = _bounds(start, end)
    trng = []
    if s: trng.append(Task.assigned_at >= s)
    if e: trng.append(Task.assigned_at <= e)

    def tcount(*conds):
        return db.execute(select(func.count()).select_from(Task.__table__).where(*conds, *trng)).scalar()

    total_tasks = tcount()
    pending = tcount(Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]))
    completed = tcount(Task.status == TaskStatus.done)
    escalated = tcount(Task.status == TaskStatus.escalated)
    missed = tcount(Task.status == TaskStatus.missed)
    total_employees = db.execute(select(func.count()).select_from(Employee.__table__).where(
        Employee.is_active == True
    )).scalar()
    on_leave = db.execute(select(func.count()).select_from(Employee.__table__).where(
        Employee.is_active == True, Employee.on_leave == True
    )).scalar()
    msg_conds = []
    if s: msg_conds.append(ConversationLog.created_at >= s)
    if e: msg_conds.append(ConversationLog.created_at <= e)
    total_messages = db.execute(select(func.count()).select_from(ConversationLog.__table__).where(*msg_conds)).scalar()
    open_tickets = db.execute(select(func.count()).select_from(EscalationTicket.__table__).where(
        EscalationTicket.status == "open"
    )).scalar()

    completion_rate = round((completed / total_tasks * 100), 1) if total_tasks > 0 else 0

    # Average resolution time (completed tasks only, within range)
    completed_tasks = db.execute(
        select(Task).where(Task.status == TaskStatus.done, Task.completed_at != None, *trng)
    ).scalars().all()
    if completed_tasks:
        total_hours = sum(
            (t.completed_at.replace(tzinfo=timezone.utc) - t.assigned_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
            for t in completed_tasks if t.completed_at and t.assigned_at
        )
        avg_resolution_hours = round(total_hours / len(completed_tasks), 1)
    else:
        avg_resolution_hours = 0

    return {
        "total_tasks": total_tasks,
        "pending_tasks": pending,
        "completed_tasks": completed,
        "escalated_tasks": escalated,
        "missed_tasks": missed,
        "total_employees": total_employees,
        "employees_on_leave": on_leave,
        "total_messages": total_messages,
        "open_escalations": open_tickets,
        "completion_rate": completion_rate,
        "avg_resolution_hours": avg_resolution_hours,
    }

@router.get("/tasks-by-department")
def tasks_by_department(start: str = None, end: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """Task distribution per department, optionally within a date range."""
    s, e = _bounds(start, end)
    trng = []
    if s: trng.append(Task.assigned_at >= s)
    if e: trng.append(Task.assigned_at <= e)
    result = db.execute(
        select(
            Employee.department,
            func.count(Task.id).label("total"),
            func.sum(case((Task.status == TaskStatus.done, 1), else_=0)).label("done"),
            func.sum(case((Task.status == TaskStatus.pending, 1), else_=0)).label("pending"),
        )
        .join(Employee, Task.assigned_to_id == Employee.id)
        .where(*trng)
        .group_by(Employee.department)
    )
    return [{"department": r[0], "total": r[1], "done": int(r[2] or 0), "pending": int(r[3] or 0)} for r in result.fetchall()]

@router.get("/tasks-by-priority")
def tasks_by_priority(start: str = None, end: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """Task distribution by priority, optionally within a date range."""
    s, e = _bounds(start, end)
    trng = []
    if s: trng.append(Task.assigned_at >= s)
    if e: trng.append(Task.assigned_at <= e)
    result = db.execute(
        select(Task.priority, func.count(Task.id))
        .where(*trng)
        .group_by(Task.priority)
    )
    return [{"priority": r[0].value, "count": r[1]} for r in result.fetchall()]

@router.get("/daily-trend")
def daily_trend(days: int = 14, start: str = None, end: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """Task creation/completion trend. Uses [start,end] if given, else last N days."""
    now = datetime.now(timezone.utc)
    s, e = _bounds(start, end)
    start = s or (now - timedelta(days=days))
    end_dt = e or now

    created = db.execute(
        select(func.date(Task.assigned_at).label("day"), func.count(Task.id))
        .where(Task.assigned_at >= start, Task.assigned_at <= end_dt)
        .group_by(func.date(Task.assigned_at))
        .order_by(func.date(Task.assigned_at))
    ).fetchall()

    completed = db.execute(
        select(func.date(Task.completed_at).label("day"), func.count(Task.id))
        .where(Task.completed_at >= start, Task.completed_at <= end_dt, Task.completed_at != None)
        .group_by(func.date(Task.completed_at))
        .order_by(func.date(Task.completed_at))
    ).fetchall()

    created_map = {str(r[0]): r[1] for r in created}
    completed_map = {str(r[0]): r[1] for r in completed}
    all_days = sorted(set(list(created_map.keys()) + list(completed_map.keys())))

    return [{"date": d, "created": created_map.get(d, 0), "completed": completed_map.get(d, 0)} for d in all_days]

@router.get("/top-performers")
def top_performers(limit: int = 10, start: str = None, end: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    """Employees with most completed tasks, optionally within a date range."""
    s, e = _bounds(start, end)
    conds = [Task.status == TaskStatus.done]
    if s: conds.append(Task.assigned_at >= s)
    if e: conds.append(Task.assigned_at <= e)
    result = db.execute(
        select(Employee.name, Employee.department, func.count(Task.id).label("completed"))
        .join(Employee, Task.assigned_to_id == Employee.id)
        .where(*conds)
        .group_by(Employee.id, Employee.name, Employee.department)
        .order_by(func.count(Task.id).desc())
        .limit(limit)
    )
    return [{"name": r[0], "department": r[1], "completed": r[2]} for r in result.fetchall()]
