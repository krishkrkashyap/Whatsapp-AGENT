"""SOP Router — CRUD for SOP definitions, department view, bulk import."""
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File
from typing import Optional
from app.database import get_db
from app.services.sop_service import SOPService
from app.routers.auth import verify_token

router = APIRouter(prefix="/api/sops", tags=["sops"])


def _get_svc(db):
    return SOPService(db)


# ── Departments ─────────────────────────────────────────────────────────────

@router.get("/departments")
async def list_sop_departments(db=Depends(get_db), _user=Depends(verify_token)):
    """Return departments that have SOPs with counts."""
    svc = _get_svc(db)
    return svc.get_departments()


# ── List SOPs ───────────────────────────────────────────────────────────────

@router.get("")
async def list_sops(
    department: Optional[str] = Query(None),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_svc(db)
    sops = svc.list_all(department=department)
    result = []
    for s in sops:
        emp_name = s.assigned_to.name if s.assigned_to else "Unknown"
        admin_name = s.admin.name if s.admin else "—"
        result.append({
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "department": s.department,
            "frequency": s.frequency.value,
            "days_of_week": s.days_of_week,
            "day_of_month": s.day_of_month,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "interval_hours": s.interval_hours,
            "assigned_to_id": s.assigned_to_id,
            "assigned_to_name": emp_name,
            "admin_id": s.admin_id,
            "admin_name": admin_name,
            "requires_attachment": s.requires_attachment,
            "attachment_checklist": s.attachment_checklist,
            "notify_before_min": s.notify_before_min,
            "notify_after_min": s.notify_after_min,
            "admin_notify_after_min": s.admin_notify_after_min,
            "priority": s.priority,
            "status": s.status.value,
            "paused_until": s.paused_until.isoformat() if s.paused_until else None,
            "created_at": str(s.created_at),
        })
    return result


# ── Get single SOP ──────────────────────────────────────────────────────────

@router.get("/{sop_id}")
async def get_sop(sop_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    svc = _get_svc(db)
    sop = svc.get_by_id(sop_id)
    if not sop:
        raise HTTPException(404, "SOP not found")
    return {
        "id": sop.id,
        "title": sop.title,
        "description": sop.description,
        "department": sop.department,
        "frequency": sop.frequency.value,
        "days_of_week": sop.days_of_week,
        "day_of_month": sop.day_of_month,
        "start_time": sop.start_time,
        "end_time": sop.end_time,
        "interval_hours": sop.interval_hours,
        "assigned_to_id": sop.assigned_to_id,
        "admin_id": sop.admin_id,
        "requires_attachment": sop.requires_attachment,
        "attachment_checklist": sop.attachment_checklist,
        "notify_before_min": sop.notify_before_min,
        "notify_after_min": sop.notify_after_min,
        "admin_notify_after_min": sop.admin_notify_after_min,
        "priority": sop.priority,
        "status": sop.status.value,
        "paused_until": sop.paused_until.isoformat() if sop.paused_until else None,
    }


# ── Create ──────────────────────────────────────────────────────────────────

@router.post("")
async def create_sop(
    data: dict = Body(...),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    required = ["title", "department", "start_time", "assigned_to_id"]
    for field in required:
        if field not in data:
            raise HTTPException(400, f"Missing required field: {field}")
    svc = _get_svc(db)
    sop = svc.create(data)
    return {"status": "created", "id": sop.id}


# ── Update ──────────────────────────────────────────────────────────────────

@router.put("/{sop_id}")
async def update_sop(
    sop_id: str,
    data: dict = Body(...),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_svc(db)
    sop = svc.update(sop_id, data)
    if not sop:
        raise HTTPException(404, "SOP not found")
    return {"status": "updated"}


# ── Bulk pause / resume ──────────────────────────────────────────────────────

@router.post("/bulk-status")
async def bulk_status(
    data: dict = Body(...),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    """Pause/resume many SOPs at once — the group off-switch.

    Body: {"status": "paused"|"active",
           "paused_until": ISO datetime|null,   # optional, only for paused
           "departments": [..],                 # match all SOPs in these depts
           "sop_ids": [..]}                     # and/or these explicit ids
    Returns {"updated": N}."""
    status = data.get("status")
    if status not in ("paused", "active", "archived"):
        raise HTTPException(400, "status must be 'paused', 'active' or 'archived'")
    departments = data.get("departments") or ([data["department"]] if data.get("department") else None)
    sop_ids = data.get("sop_ids")
    if not departments and not sop_ids:
        raise HTTPException(400, "Provide 'departments' and/or 'sop_ids'")
    svc = _get_svc(db)
    n = svc.bulk_set_status(status, paused_until=data.get("paused_until"),
                            departments=departments, sop_ids=sop_ids)
    return {"updated": n}


# ── Delete ──────────────────────────────────────────────────────────────────

@router.delete("/{sop_id}")
async def delete_sop(sop_id: str, db=Depends(get_db), _user=Depends(verify_token)):
    svc = _get_svc(db)
    if not svc.delete(sop_id):
        raise HTTPException(404, "SOP not found")
    return {"status": "deleted"}


# ── Bulk Import ─────────────────────────────────────────────────────────────

@router.post("/import")
async def import_sops(
    items: list = Body(..., description="Array of SOP objects"),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_svc(db)
    return svc.bulk_create_from_list(items)


@router.post("/import-xlsx")
async def import_sops_xlsx(
    file: UploadFile = File(..., description="SOP roster .xlsx"),
    priority: str = Query("medium"),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    """Upload the SOP roster sheet. Auto-creates/links employees by WhatsApp
    number, normalizes times, and maps 'every N hours' to interval SOPs."""
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an .xlsx file")
    content = await file.read()
    svc = _get_svc(db)
    return svc.import_from_xlsx(content, default_priority=priority)


# ── Executions ──────────────────────────────────────────────────────────────

@router.get("/{sop_id}/executions")
async def list_executions(
    sop_id: str,
    limit: int = Query(50),
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    svc = _get_svc(db)
    execs = svc.get_executions(sop_id=sop_id, limit=limit)
    return [{
        "id": e.id,
        "sop_id": e.sop_id,
        "task_id": e.task_id,
        "scheduled_date": e.scheduled_date,
        "status": e.status,
        "notified_at": str(e.notified_at) if e.notified_at else None,
        "completed_at": str(e.completed_at) if e.completed_at else None,
        "escalated_at": str(e.escalated_at) if e.escalated_at else None,
    } for e in execs]


# ── Employee lookup for SOP assignment ─────────────────────────────────────

@router.get("/employees/list")
async def list_employees_for_sop(db=Depends(get_db), _user=Depends(verify_token)):
    from app.models.employee import Employee
    from sqlalchemy import select
    result = db.execute(select(Employee).where(Employee.is_active == True))
    emps = result.scalars().all()
    return [{
        "id": e.id,
        "name": e.name,
        "department": e.department,
        "role": e.role,
        "whatsapp_number": e.whatsapp_number,
        "is_admin": e.is_admin,
    } for e in emps]
