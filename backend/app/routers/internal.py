"""Internal router — BUG-3,10,13 fixes + auth guards."""
import logging
from fastapi import APIRouter, Depends
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from app.database import get_db
from app.models.task import Task, FollowUp, TaskStatus
from app.models.employee import Employee
from app.services.employee_svc import EmployeeService
from app.services.whatsapp import send_whatsapp
from app.routers.auth import verify_token
from pydantic import BaseModel

logger = logging.getLogger("internal")
router = APIRouter(prefix="/internal")

@router.post("/check-due-tasks")
def check_due_tasks(db=Depends(get_db), _user=Depends(verify_token)):
    """BUG-13 fix: Now requires auth."""
    now = datetime.now(timezone.utc)
    result = db.execute(
        select(Task).where(
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            Task.due_date != None,
            Task.due_date <= now,
        )
    )
    overdue = list(result.scalars().all())
    emp_svc = EmployeeService(db)
    reminded = []
    for task in overdue:
        if task.last_follow_up_at and (now - task.last_follow_up_at).total_seconds() < 3600:
            continue
        emp = emp_svc.get_by_id(task.assigned_to_id)
        if emp:
            try:
                send_whatsapp(emp.whatsapp_number,
                    f"⏰ *Reminder:* Task \"{task.title}\" is due!\n"
                    f"Priority: {task.priority.value.upper()}\n\n"
                    f"Reply 'done' if completed, or describe issue for help.")
                task.last_follow_up_at = now
                reminded.append(task.id)
            except Exception as e:
                logger.error(f"Reminder failed for {emp.name}: {e}")
    db.commit()
    return {"reminded": len(reminded), "overdue": len(overdue)}

@router.post("/check-periodic-followups")
def check_periodic(db=Depends(get_db), _user=Depends(verify_token)):
    now = datetime.now(timezone.utc)
    result = db.execute(
        select(FollowUp).where(FollowUp.next_trigger_at <= now)
    )
    followups = list(result.scalars().all())
    emp_svc = EmployeeService(db)
    reminded = []
    for fu in followups:
        task_result = db.execute(select(Task).where(Task.id == fu.task_id))
        task = task_result.scalar_one_or_none()
        if not task or task.status == TaskStatus.done:
            continue
        emp = emp_svc.get_by_id(task.assigned_to_id)
        if emp:
            try:
                send_whatsapp(emp.whatsapp_number,
                    f"🔄 *Follow-up:* Task \"{task.title}\" still pending.\n\n"
                    f"Reply 'done' or describe issue.")
                reminded.append(task.id)
            except Exception:
                pass
        if fu.interval_hours:
            fu.next_trigger_at = now + timedelta(hours=fu.interval_hours)
        else:
            fu.next_trigger_at = now + timedelta(days=1)
    db.commit()
    return {"reminded": len(reminded)}

@router.post("/check-sla-escalation")
def check_sla(db=Depends(get_db), _user=Depends(verify_token)):
    """BUG-10 fix: Removed redundant filter condition.
    Now honors the configurable sla_hours setting and skips tasks with a
    future deadline (consistent with the background scheduler)."""
    from app.routers.settings import get_int_setting
    now = datetime.now(timezone.utc)
    sla_hours = get_int_setting(db, "sla_hours", 4)
    sla_time = now - timedelta(hours=sla_hours)
    result = db.execute(
        select(Task).where(
            Task.status == TaskStatus.pending,
            Task.assigned_at <= sla_time,
        )
    )
    overdue_sla = [
        t for t in result.scalars().all()
        if not (t.due_date and t.due_date > now)
    ]
    emp_svc = EmployeeService(db)
    from app.models.escalation import EscalationTicket, EscalationStatus

    escalated_count = 0

    for task in overdue_sla:
        task.status = TaskStatus.escalated
        emp = emp_svc.get_by_id(task.assigned_to_id)
        emp_name = emp.name if emp else "Unknown"

        ticket = EscalationTicket(
            employee_id=task.assigned_to_id,
            task_id=task.id,
            original_query=f"SLA Breach: Task '{task.title}' not started within {sla_hours} hours.",
            status=EscalationStatus.open,
        )
        db.add(ticket)

        # Notify ONLY this task's admin (its assigner), not every admin.
        task_admin = emp_svc.get_by_id(task.assigned_by_id) if task.assigned_by_id else None
        recipients = emp_svc.resolve_escalation_recipients(task_admin)
        for admin in recipients:
            try:
                send_whatsapp(admin.whatsapp_number,
                    f"⚠️ *SLA Breach Escalation*\n\n"
                    f"Task: {task.title}\n"
                    f"Assigned to: {emp_name}\n"
                    f"Status: Not started for > {sla_hours} hours!")
            except Exception:
                pass

        escalated_count += 1

    db.commit()
    return {"escalated": escalated_count}

@router.get("/stats")
def internal_stats(db=Depends(get_db), _user=Depends(verify_token)):
    """BUG-3 + SEC-1 fix: Now returns total_employees and requires auth."""
    total_emp = db.execute(
        select(func.count()).select_from(Employee.__table__)
    ).scalar()

    pending = db.execute(
        select(func.count()).select_from(Task.__table__).where(
            Task.status.in_([TaskStatus.pending, TaskStatus.in_progress])
        )
    ).scalar()

    done_count = db.execute(
        select(func.count()).select_from(Task.__table__).where(
            Task.status == TaskStatus.done
        )
    ).scalar()

    escalated_count = db.execute(
        select(func.count()).select_from(Task.__table__).where(
            Task.status == TaskStatus.escalated
        )
    ).scalar()

    return {
        "total_employees": total_emp,
        "pending_tasks": pending,
        "completed_tasks": done_count,
        "escalated_tasks": escalated_count,
    }

@router.get("/departments")
def list_departments(db=Depends(get_db), _user=Depends(verify_token)):
    """F-4: Dynamic department list from database."""
    emp_svc = EmployeeService(db)
    return {"departments": emp_svc.get_departments()}

class BroadcastRequest(BaseModel):
    message: str
    department: str = "all"

@router.post("/broadcast")
def broadcast_message(req: BroadcastRequest, db=Depends(get_db), _user=Depends(verify_token)):
    """BUG-13 fix: Now requires auth."""
    query = select(Employee).where(Employee.is_active == True)
    if req.department and req.department != "all":
        query = query.where(Employee.department == req.department)

    employees = list(db.execute(query).scalars().all())
    sent = 0
    for emp in employees:
        try:
            send_whatsapp(emp.whatsapp_number, f"📢 *Broadcast from Admin*\n\n{req.message}")
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to {emp.name}: {e}")

    # F-14: Audit trail
    from app.services.audit import AuditService
    AuditService(db).log(
        action="broadcast.send",
        resource_type="broadcast",
        actor_name=_user,
        details={"message": req.message[:200], "department": req.department, "sent": sent},
    )

    return {"status": "success", "sent": sent}
