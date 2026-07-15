from datetime import datetime, timezone
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid
import enum

class Direction(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"

class MessageType(str, enum.Enum):
    assignment = "assignment"
    reply = "reply"
    trouble = "trouble"
    followup = "followup"
    status_check = "status_check"
    help = "help"
    escalation = "escalation"

class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    message_text: Mapped[str] = mapped_column(Text)
    direction: Mapped[Direction] = mapped_column(SAEnum(Direction))
    message_type: Mapped[MessageType] = mapped_column(SAEnum(MessageType))
    language: Mapped[str] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
