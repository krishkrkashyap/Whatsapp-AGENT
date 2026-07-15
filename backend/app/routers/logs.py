"""F-6: Conversation log viewer + F-14: Audit trail viewer."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from app.database import get_db
from app.models.conversation import ConversationLog
from app.models.employee import Employee
from app.models.audit_log import AuditLog
from app.routers.auth import verify_token

router = APIRouter()

@router.get("/conversations")
def list_conversations(employee_id: str = None, limit: int = 100, db=Depends(get_db), _user=Depends(verify_token)):
    """F-6: View WhatsApp conversation history."""
    query = select(ConversationLog).order_by(ConversationLog.created_at.desc())
    if employee_id:
        query = query.where(ConversationLog.employee_id == employee_id)
    query = query.limit(limit)
    result = db.execute(query)
    logs = result.scalars().all()

    emp_cache = {}
    def get_emp_name(eid):
        if eid not in emp_cache:
            e = db.execute(select(Employee).where(Employee.id == eid)).scalar_one_or_none()
            emp_cache[eid] = e.name if e else "Unknown"
        return emp_cache[eid]

    return [{
        "id": l.id,
        "task_id": l.task_id,
        "employee_id": l.employee_id,
        "employee_name": get_emp_name(l.employee_id),
        "message_text": l.message_text,
        "direction": l.direction.value,
        "message_type": l.message_type.value,
        "language": l.language,
        "created_at": str(l.created_at),
    } for l in logs]

@router.get("/audit")
def list_audit_logs(limit: int = 100, db=Depends(get_db), _user=Depends(verify_token)):
    """F-14: View audit trail."""
    result = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    return [{
        "id": l.id,
        "actor_name": l.actor_name,
        "action": l.action,
        "resource_type": l.resource_type,
        "resource_id": l.resource_id,
        "details": l.details,
        "created_at": str(l.created_at),
    } for l in logs]
