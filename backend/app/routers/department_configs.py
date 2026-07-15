"""Department Configs Router — per-department SLA toggle and reminder time."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from app.database import get_db
from app.models.department_config import DepartmentConfig
from app.routers.auth import verify_token

router = APIRouter(prefix="/api/department-configs", tags=["department-configs"])


class UpsertConfigRequest(BaseModel):
    reminder_time: Optional[str] = None  # HH:MM or null
    sla_enabled: Optional[bool] = None


@router.get("/")
def list_configs(db=Depends(get_db), _user=Depends(verify_token)):
    """List all department configs."""
    result = db.execute(select(DepartmentConfig).order_by(DepartmentConfig.department))
    configs = result.scalars().all()
    return [{
        "department": c.department,
        "reminder_time": c.reminder_time,
        "sla_enabled": c.sla_enabled,
        "last_reminder_date": c.last_reminder_date,
    } for c in configs]


@router.put("/{department}")
def upsert_config(
    department: str,
    req: UpsertConfigRequest,
    db=Depends(get_db),
    _user=Depends(verify_token),
):
    """Create or update config for a department."""
    result = db.execute(select(DepartmentConfig).where(DepartmentConfig.department == department))
    config = result.scalar_one_or_none()

    if not config:
        config = DepartmentConfig(department=department)
        db.add(config)

    if req.reminder_time is not None:
        config.reminder_time = req.reminder_time if req.reminder_time else None
    if req.sla_enabled is not None:
        config.sla_enabled = req.sla_enabled

    db.commit()
    db.refresh(config)
    return {
        "department": config.department,
        "reminder_time": config.reminder_time,
        "sla_enabled": config.sla_enabled,
    }
