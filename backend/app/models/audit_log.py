from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, JSON
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid

class AuditLog(Base):
    """F-14: Audit trail — tracks all admin actions."""
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(String(36), nullable=True)  # who performed the action
    actor_name: Mapped[str] = mapped_column(String(200), nullable=True)
    action: Mapped[str] = mapped_column(String(100))  # e.g. "task.assign", "employee.create", "broadcast.send"
    resource_type: Mapped[str] = mapped_column(String(50))  # e.g. "task", "employee", "kb_document"
    resource_id: Mapped[str] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=True)  # extra context
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
