from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum, DateTime
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid
import enum

class EscalationStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"

class EscalationTicket(Base):
    __tablename__ = "escalation_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    original_query: Mapped[str] = mapped_column(Text)
    bot_attempted_solution: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[EscalationStatus] = mapped_column(SAEnum(EscalationStatus), default=EscalationStatus.open)
    assigned_to_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
