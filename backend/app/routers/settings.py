"""System settings API — admin-configurable toggles like direct escalation."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from app.database import get_db
from app.models.system_settings import SystemSetting
from app.routers.auth import verify_token

router = APIRouter()

# Default settings (seeded if missing)
DEFAULTS = {
    "direct_escalation": {
        "value": "false",
        "description": "Skip KB/AI search and directly escalate help requests to admins"
    },
    "escalation_notify_employee_details": {
        "value": "true",
        "description": "Include task details and contact info in escalation notifications"
    },
    "auto_followup_enabled": {
        "value": "true",
        "description": "Enable automatic follow-up reminders for overdue tasks"
    },
    "sla_hours": {
        "value": "4",
        "description": "Hours before a pending task triggers SLA escalation"
    },
    "sla_enabled": {
        "value": "true",
        "description": "Enable SLA escalation for overdue tasks (master switch)"
    },
    "escalation_recipient": {
        "value": "",
        "description": "WhatsApp number of the single admin who receives escalations not tied to a task. Empty = first admin only (never all admins)."
    },
}

def _get_setting(db, key: str) -> str:
    """Get a setting value, seeding the default if it doesn't exist."""
    result = db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    # Seed default
    if key in DEFAULTS:
        s = SystemSetting(key=key, value=DEFAULTS[key]["value"], description=DEFAULTS[key]["description"])
        db.add(s)
        db.commit()
        return DEFAULTS[key]["value"]
    return ""

def get_bool_setting(db, key: str) -> bool:
    """Helper to get a boolean setting."""
    return _get_setting(db, key).lower() in ("true", "1", "yes")

def get_int_setting(db, key: str, default: int = 0) -> int:
    """Helper to get an integer setting."""
    try:
        return int(_get_setting(db, key))
    except (ValueError, TypeError):
        return default

def get_str_setting(db, key: str, default: str = "") -> str:
    """Helper to get a string setting, falling back to default if unset/empty."""
    val = _get_setting(db, key)
    return val if val else default

@router.get("/")
def get_all_settings(db=Depends(get_db), _user=Depends(verify_token)):
    """Get all system settings."""
    # Ensure all defaults exist
    for key in DEFAULTS:
        _get_setting(db, key)
    
    result = db.execute(select(SystemSetting).order_by(SystemSetting.key))
    settings = result.scalars().all()
    return [{"key": s.key, "value": s.value, "description": s.description} for s in settings]

class UpdateSettingRequest(BaseModel):
    value: str

@router.put("/{key}")
def update_setting(key: str, req: UpdateSettingRequest, db=Depends(get_db), _user=Depends(verify_token)):
    """Update a single setting."""
    result = db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = req.value
    else:
        setting = SystemSetting(key=key, value=req.value, description=DEFAULTS.get(key, {}).get("description", ""))
        db.add(setting)
    db.commit()

    from app.services.audit import AuditService
    AuditService(db).log(
        action="settings.update", resource_type="setting", resource_id=key,
        actor_name=_user, details={"value": req.value}
    )
    return {"key": key, "value": req.value}
