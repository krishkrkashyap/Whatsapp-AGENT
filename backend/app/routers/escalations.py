"""F-7: Escalation dashboard router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from app.database import get_db
from app.models.escalation import EscalationTicket, EscalationStatus
from app.models.employee import Employee
from app.routers.auth import verify_token
from app.services.audit import AuditService
from datetime import datetime, timezone

router = APIRouter()

@router.get("/")
def list_escalations(status: str = None, db=Depends(get_db), _user=Depends(verify_token)):
    query = select(EscalationTicket).order_by(EscalationTicket.created_at.desc())
    if status:
        query = query.where(EscalationTicket.status == EscalationStatus(status))
    result = db.execute(query)
    tickets = result.scalars().all()

    emp_cache = {}
    def get_emp_name(eid):
        if eid not in emp_cache:
            e = db.execute(select(Employee).where(Employee.id == eid)).scalar_one_or_none()
            emp_cache[eid] = e.name if e else "Unknown"
        return emp_cache[eid]

    return [{
        "id": t.id,
        "task_id": t.task_id,
        "employee_id": t.employee_id,
        "employee_name": get_emp_name(t.employee_id),
        "original_query": t.original_query,
        "bot_attempted_solution": t.bot_attempted_solution,
        "status": t.status.value,
        "assigned_to_id": t.assigned_to_id,
        "resolved_at": str(t.resolved_at) if t.resolved_at else None,
        "created_at": str(t.created_at),
    } for t in tickets]

@router.post("/{ticket_id}/resolve")
def resolve_escalation(ticket_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    result = db.execute(select(EscalationTicket).where(EscalationTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    ticket.status = EscalationStatus.resolved
    ticket.resolved_at = datetime.now(timezone.utc)
    db.commit()
    AuditService(db).log(
        action="escalation.resolve", resource_type="escalation", resource_id=ticket_id,
        actor_name=_user
    )
    return {"status": "resolved"}

@router.post("/{ticket_id}/assign")
def assign_escalation(ticket_id: str, assignee_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    result = db.execute(select(EscalationTicket).where(EscalationTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    ticket.assigned_to_id = assignee_id
    ticket.status = EscalationStatus.in_progress
    db.commit()

    from app.services.whatsapp import send_whatsapp
    from app.services.employee_svc import EmployeeService
    emp_svc = EmployeeService(db)
    assignee = emp_svc.get_by_id(assignee_id)
    if assignee:
        send_whatsapp(assignee.whatsapp_number,
            f"🆘 *Escalation Assigned to You*\n\n{ticket.original_query}")
    return {"status": "assigned"}
