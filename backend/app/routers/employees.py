"""Employees router — F-2 deactivate + F-20 registration approval + F-14 audit."""
import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from app.database import get_db
from app.models.employee import Employee
from app.models.task import Task, FollowUp
from app.models.conversation import ConversationLog
from app.models.escalation import EscalationTicket
from app.services.employee_svc import EmployeeService
from app.services.audit import AuditService
from app.routers.auth import verify_token

logger = logging.getLogger("employees")

class CreateEmployeeRequest(BaseModel):
    name: str
    department: str
    role: str
    whatsapp_number: str
    is_admin: bool = False

class UpdateEmployeeRequest(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    whatsapp_number: Optional[str] = None
    is_admin: Optional[bool] = None

router = APIRouter()

@router.get("/")
async def list_employees(db=Depends(get_db), _user=Depends(verify_token)):
    """SEC-1 fix: Now requires auth."""
    svc = EmployeeService(db)
    emps = svc.list_all()
    return [{"id": e.id, "name": e.name, "department": e.department,
             "role": e.role, "whatsapp_number": e.whatsapp_number,
             "is_admin": e.is_admin, "is_active": e.is_active,
             "on_leave": getattr(e, 'on_leave', False),
             "access_role": e.access_role.value if hasattr(e, 'access_role') and e.access_role else "employee",
             "registered_via": getattr(e, 'registered_via', 'admin'),
             "created_at": str(e.created_at) if e.created_at else None} for e in emps]

@router.get("/all")
async def list_all_employees(db=Depends(get_db), _user=Depends(verify_token)):
    """Include inactive employees for admin view."""
    svc = EmployeeService(db)
    emps = svc.list_all_including_inactive()
    return [{"id": e.id, "name": e.name, "department": e.department,
             "role": e.role, "whatsapp_number": e.whatsapp_number,
             "is_admin": e.is_admin, "is_active": e.is_active,
             "on_leave": getattr(e, 'on_leave', False),
             "registered_via": getattr(e, 'registered_via', 'admin'),
             "created_at": str(e.created_at) if e.created_at else None} for e in emps]

@router.get("/count")
async def employee_count(db=Depends(get_db), _user=Depends(verify_token)):
    """SEC-1 + SEC-5 fix: Now requires auth and uses COUNT(*) instead of loading all rows."""
    from sqlalchemy import func, select as sa_select
    count = db.execute(
        sa_select(func.count()).select_from(Employee.__table__).where(Employee.is_active == True)
    ).scalar()
    return {"count": count}

@router.get("/departments")
async def get_departments(db=Depends(get_db), _user=Depends(verify_token)):
    """F-4 + SEC-1 fix: Dynamic department list, now requires auth."""
    svc = EmployeeService(db)
    return {"departments": svc.get_departments(), "stats": svc.get_department_stats()}

@router.post("/")
async def create_employee(req: CreateEmployeeRequest, db=Depends(get_db), _user=Depends(verify_token)):
    from app.utils.helpers import normalize_phone
    svc = EmployeeService(db)

    number = normalize_phone(req.whatsapp_number)
    existing = svc.get_by_whatsapp(number)
    if existing:
        raise HTTPException(400, f"Employee with number {number} already exists")

    emp = Employee(
        name=req.name,
        department=req.department,
        role=req.role,
        whatsapp_number=number,
        is_admin=req.is_admin,
        is_active=True,
        registered_via="admin",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)

    AuditService(db).log(
        action="employee.create", resource_type="employee", resource_id=emp.id,
        actor_name=_user, details={"name": emp.name, "department": emp.department}
    )

    return {"id": emp.id, "name": emp.name, "department": emp.department,
            "role": emp.role, "whatsapp_number": emp.whatsapp_number,
            "is_admin": emp.is_admin, "is_active": emp.is_active}

@router.put("/{emp_id}")
async def update_employee(emp_id: str, req: UpdateEmployeeRequest, db=Depends(get_db), _user=Depends(verify_token)):
    from app.utils.helpers import normalize_phone
    svc = EmployeeService(db)
    updates = req.model_dump(exclude_unset=True)
    if updates.get("whatsapp_number"):
        updates["whatsapp_number"] = normalize_phone(updates["whatsapp_number"])
    emp = svc.update_employee(emp_id, **updates)
    if not emp:
        raise HTTPException(404, "Employee not found")
    AuditService(db).log(
        action="employee.update", resource_type="employee", resource_id=emp_id,
        actor_name=_user, details=updates
    )
    return {"id": emp.id, "name": emp.name, "department": emp.department,
            "role": emp.role, "whatsapp_number": emp.whatsapp_number,
            "is_admin": emp.is_admin, "is_active": emp.is_active}

@router.post("/{emp_id}/deactivate")
async def deactivate_employee(emp_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    """F-2: Deactivate (soft-delete) an employee."""
    svc = EmployeeService(db)
    if svc.deactivate(emp_id):
        AuditService(db).log(
            action="employee.deactivate", resource_type="employee", resource_id=emp_id,
            actor_name=_user,
        )
        return {"status": "deactivated"}
    raise HTTPException(404, "Employee not found")

@router.post("/{emp_id}/activate")
async def activate_employee(emp_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    """F-2: Reactivate an employee."""
    svc = EmployeeService(db)
    if svc.activate(emp_id):
        AuditService(db).log(
            action="employee.activate", resource_type="employee", resource_id=emp_id,
            actor_name=_user,
        )
        return {"status": "activated"}
    raise HTTPException(404, "Employee not found")

@router.delete("/{emp_id}")
async def delete_employee(emp_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    """Hard-delete an employee. Cascades to tasks, convos, escalations."""
    from sqlalchemy import delete as sa_delete

    emp = db.execute(select(Employee).where(Employee.id == emp_id)).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")

    try:
        from sqlalchemy import update as sa_update, delete as _sa_delete
        from app.models.sop import SOPDefinition, SOPExecution

        # Cascade-delete in FK-safe order
        task_ids = [
            row[0] for row in db.execute(
                select(Task.id).where(
                    (Task.assigned_to_id == emp_id) | (Task.assigned_by_id == emp_id)
                )
            ).all()
        ]

        # SOPs referencing this employee (FKs have no ondelete, so clean manually,
        # else the delete raises IntegrityError). Executions first (they FK both
        # the employee and the tasks we're about to delete), then the SOP defs the
        # employee owns; for SOPs where they're only the escalation admin, null it.
        sop_ids = [
            row[0] for row in db.execute(
                select(SOPDefinition.id).where(SOPDefinition.assigned_to_id == emp_id)
            ).all()
        ]
        exec_cond = (SOPExecution.assigned_to_id == emp_id)
        if sop_ids:
            exec_cond = exec_cond | (SOPExecution.sop_id.in_(sop_ids))
        if task_ids:
            exec_cond = exec_cond | (SOPExecution.task_id.in_(task_ids))
        db.execute(_sa_delete(SOPExecution).where(exec_cond))
        if sop_ids:
            db.execute(_sa_delete(SOPDefinition).where(SOPDefinition.id.in_(sop_ids)))
        db.execute(
            sa_update(SOPDefinition).where(SOPDefinition.admin_id == emp_id).values(admin_id=None)
        )

        if task_ids:
            db.execute(sa_delete(FollowUp).where(FollowUp.task_id.in_(task_ids)))
            db.execute(
                sa_delete(EscalationTicket).where(
                    (EscalationTicket.task_id.in_(task_ids)) |
                    (EscalationTicket.employee_id == emp_id) |
                    (EscalationTicket.assigned_to_id == emp_id)
                )
            )
            db.execute(
                sa_delete(ConversationLog).where(
                    (ConversationLog.task_id.in_(task_ids)) |
                    (ConversationLog.employee_id == emp_id)
                )
            )
            db.execute(sa_delete(Task).where(Task.id.in_(task_ids)))
        else:
            db.execute(
                sa_delete(EscalationTicket).where(
                    (EscalationTicket.employee_id == emp_id) |
                    (EscalationTicket.assigned_to_id == emp_id)
                )
            )
            db.execute(
                sa_delete(ConversationLog).where(ConversationLog.employee_id == emp_id)
            )

        db.delete(emp)
        db.commit()

        AuditService(db).log(
            action="employee.delete", resource_type="employee", resource_id=emp_id,
            actor_name=_user,
        )
        return {"status": "deleted"}

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete employee {emp_id}: {e}")
        raise HTTPException(400, f"Cannot delete: employee has active references. Deactivate instead.")

@router.post("/import")
async def import_employees(file: UploadFile = File(...), db=Depends(get_db), _user=Depends(verify_token)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files supported")
    content = (await file.read()).decode("utf-8")
    svc = EmployeeService(db)
    count = svc.import_csv(content)
    AuditService(db).log(
        action="employee.import", resource_type="employee",
        actor_name=_user, details={"filename": file.filename, "imported": count}
    )
    return {"imported": count}

# F-20: Pending registration endpoints
from app.models.pending_registration import PendingRegistration, RegistrationStatus
from sqlalchemy import select

@router.get("/registrations/pending")
async def get_pending_registrations(db=Depends(get_db), _user=Depends(verify_token)):
    result = db.execute(
        select(PendingRegistration).where(PendingRegistration.status == RegistrationStatus.pending)
        .order_by(PendingRegistration.created_at.desc())
    )
    regs = result.scalars().all()
    return [{"id": r.id, "name": r.name, "whatsapp_number": r.whatsapp_number,
             "department": r.department, "status": r.status.value,
             "created_at": str(r.created_at)} for r in regs]

@router.post("/registrations/{reg_id}/approve")
async def approve_registration(reg_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    result = db.execute(select(PendingRegistration).where(PendingRegistration.id == reg_id))
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(404, "Registration not found")

    # whatsapp_number is UNIQUE on employees — inserting a duplicate raises
    # IntegrityError (500). Guard: if the number already exists, reactivate that
    # employee instead of crashing, and close the registration.
    existing = db.execute(
        select(Employee).where(Employee.whatsapp_number == reg.whatsapp_number)
    ).scalar_one_or_none()
    if existing:
        if not existing.is_active:
            existing.is_active = True
        reg.status = RegistrationStatus.approved
        reg.reviewed_by = _user
        db.commit()
        AuditService(db).log(
            action="employee.approve_registration", resource_type="employee", resource_id=existing.id,
            actor_name=_user, details={"from_registration": reg_id, "reactivated_existing": True},
        )
        return {"status": "approved", "employee_id": existing.id, "note": "existing employee reactivated"}

    emp = Employee(
        name=reg.name,
        department=reg.department,
        role=reg.role,
        whatsapp_number=reg.whatsapp_number,
        is_admin=False,
        is_active=True,
        registered_via="self_register",
    )
    db.add(emp)
    reg.status = RegistrationStatus.approved
    reg.reviewed_by = _user
    db.commit()
    db.refresh(emp)

    from app.services.whatsapp import send_whatsapp
    send_whatsapp(emp.whatsapp_number,
        f"🎉 Welcome {emp.name}!\n\nAapka registration approve ho gaya hai.\n"
        f"Ab aap WhatsApp se tasks receive kar sakte hain.\n\nType 'help' for commands.")

    AuditService(db).log(
        action="employee.approve_registration", resource_type="employee", resource_id=emp.id,
        actor_name=_user, details={"from_registration": reg_id}
    )
    return {"status": "approved", "employee_id": emp.id}

@router.post("/registrations/{reg_id}/reject")
async def reject_registration(reg_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    result = db.execute(select(PendingRegistration).where(PendingRegistration.id == reg_id))
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(404, "Registration not found")
    reg.status = RegistrationStatus.rejected
    reg.reviewed_by = _user
    db.commit()
    return {"status": "rejected"}
