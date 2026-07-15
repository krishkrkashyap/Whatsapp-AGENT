from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    assigned_to_id: str
    due_date: Optional[datetime] = None
    follow_up_type: str = "none"
    follow_up_interval_hours: Optional[int] = None

class TaskUpdate(BaseModel):
    """All fields optional — only provided fields are updated."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    assigned_to_id: Optional[str] = None
    requires_attachment: Optional[bool] = None
    sla_enabled: Optional[bool] = None
    # Explicit sentinel for clearing due_date
    clear_due_date: Optional[bool] = None

class TaskOut(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    assigned_to_id: str
    assigned_by_id: Optional[str] = None
    due_date: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
