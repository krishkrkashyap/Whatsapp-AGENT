from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Boolean
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid


class DepartmentConfig(Base):
    """Per-department SLA and daily reminder configuration."""
    __tablename__ = "department_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    department: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    reminder_time: Mapped[str] = mapped_column(String(5), nullable=True)  # HH:MM, null = no reminder
    sla_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_reminder_date: Mapped[str] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                                 onupdate=lambda: datetime.now(timezone.utc))
