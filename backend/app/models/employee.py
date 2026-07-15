from sqlalchemy import String, Boolean, Enum as SAEnum
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid
import enum
from datetime import datetime, timezone

class AccessRole(str, enum.Enum):
    superadmin = "superadmin"
    manager = "manager"
    team_lead = "team_lead"
    employee = "employee"

class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(100))  # job title
    access_role: Mapped[AccessRole] = mapped_column(SAEnum(AccessRole), default=AccessRole.employee)
    whatsapp_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Self-service leave: when True, the bot sends no SOP tasks/reminders to
    # them. Toggled by texting "on leave" / "back". ponytail: boolean toggle,
    # add a leave_until date if auto-return is ever needed.
    on_leave: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    org_id: Mapped[str] = mapped_column(String(100), default="default", index=True)
    registered_via: Mapped[str] = mapped_column(String(20), default="admin")  # admin, csv, self_register
    # Last non-English language this employee wrote in — used to localize bot
    # notifications sent TO them (task assignments, reminders, completion pings).
    preferred_language: Mapped[str] = mapped_column(String(20), default="english")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
