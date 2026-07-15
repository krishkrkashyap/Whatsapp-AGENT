from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, Float, ForeignKey, Enum as SAEnum, Boolean
from sqlalchemy.orm import mapped_column, Mapped, relationship
from app.database import Base
import uuid
import enum

class Priority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"

class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"
    escalated = "escalated"
    missed = "missed"  # SOP task not completed on its day — rolled over as missed

class FollowUpType(str, enum.Enum):
    none = "none"
    due_date = "due_date"
    periodic = "periodic"

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority), default=Priority.medium)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), default=TaskStatus.pending)

    assigned_by_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    assigned_to_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))

    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    follow_up_type: Mapped[FollowUpType] = mapped_column(SAEnum(FollowUpType), default=FollowUpType.none)
    follow_up_interval_hours: Mapped[float] = mapped_column(Float, nullable=True)
    last_follow_up_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    requires_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    attachment_url: Mapped[str] = mapped_column(String(500), nullable=True)  # F-19: file attachments
    bulk_group_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)  # F-18: bulk assignment
    # JSON array of checklist item names; non-empty => multi-attachment mode.
    # Copied from the originating SOP; not user-editable on one-off tasks.
    attachment_checklist: Mapped[str] = mapped_column(Text, nullable=True)

    assigned_by = relationship("Employee", foreign_keys=[assigned_by_id])
    assigned_to = relationship("Employee", foreign_keys=[assigned_to_id])

class FollowUp(Base):
    __tablename__ = "follow_ups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    type: Mapped[FollowUpType] = mapped_column(SAEnum(FollowUpType))
    next_trigger_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_hours: Mapped[float] = mapped_column(Float, nullable=True)
