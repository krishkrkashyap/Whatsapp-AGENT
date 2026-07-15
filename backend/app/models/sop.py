from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, Float, ForeignKey, Enum as SAEnum, Boolean, Time
from sqlalchemy.orm import mapped_column, Mapped, relationship
from app.database import Base
import uuid
import enum


class Frequency(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    weekday = "weekday"  # Mon-Fri only
    hourly = "hourly"    # every interval_hours between start_time and end_time


class SOPStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    archived = "archived"


class SOPDefinition(Base):
    """Template for recurring SOP tasks."""
    __tablename__ = "sop_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    department: Mapped[str] = mapped_column(String(100), index=True)
    frequency: Mapped[Frequency] = mapped_column(SAEnum(Frequency), default=Frequency.daily)
    # Days of week for weekly frequency (bitmask: 1=Mon, 2=Tue, 4=Wed, 8=Thu, 16=Fri, 32=Sat, 64=Sun)
    days_of_week: Mapped[int] = mapped_column(Integer, nullable=True)
    # Day of month for monthly frequency (1-31)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=True)

    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM (local, app_timezone)
    end_time: Mapped[str] = mapped_column(String(5), nullable=True)  # HH:MM — upper bound for interval SOPs

    # Intra-day recurrence: when set, the SOP fires every `interval_hours` from
    # start_time up to end_time (or 23:59). e.g. start 08:00 + interval 4 ->
    # 08:00, 12:00, 16:00, 20:00. None = single daily fire at start_time.
    interval_hours: Mapped[float] = mapped_column(Float, nullable=True)

    assigned_to_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    admin_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=True)
    requires_attachment: Mapped[bool] = mapped_column(Boolean, default=False)

    # Notification timing (all in minutes)
    notify_before_min: Mapped[int] = mapped_column(Integer, default=5)   # Notify N min before start
    notify_after_min: Mapped[int] = mapped_column(Integer, default=5)    # Check N min after start
    admin_notify_after_min: Mapped[int] = mapped_column(Integer, default=15)  # Escalate after N min no response

    priority: Mapped[str] = mapped_column(String(10), default="medium")  # high, medium, low
    status: Mapped[SOPStatus] = mapped_column(SAEnum(SOPStatus), default=SOPStatus.active)
    # When set and status=paused, the scheduler auto-reactivates the SOP once
    # now >= paused_until (timed "off for a period"). NULL = indefinite manual pause.
    paused_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                                 onupdate=lambda: datetime.now(timezone.utc))

    # Last date this SOP was triggered (to avoid double-trigger)
    last_triggered_date: Mapped[str] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    # JSON array of checklist item names requiring one photo each.
    attachment_checklist: Mapped[str] = mapped_column(Text, nullable=True)

    # Relationships
    assigned_to = relationship("Employee", foreign_keys=[assigned_to_id])
    admin = relationship("Employee", foreign_keys=[admin_id])


class SOPExecution(Base):
    """Tracks each SOP task instance - when it was created, notified, completed."""
    __tablename__ = "sop_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sop_id: Mapped[str] = mapped_column(ForeignKey("sop_definitions.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    assigned_to_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))

    scheduled_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    # Slot time (HH:MM) within the day. Lets interval SOPs have multiple
    # executions per date (one per fire). Empty/NULL for legacy single-fire rows.
    scheduled_time: Mapped[str] = mapped_column(String(5), nullable=True, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, notified, done, escalated

    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    sop = relationship("SOPDefinition")
    task = relationship("Task")
    assigned_to = relationship("Employee", foreign_keys=[assigned_to_id])
