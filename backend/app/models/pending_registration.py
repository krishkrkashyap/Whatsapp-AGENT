from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, Enum as SAEnum
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid
import enum

class RegistrationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class PendingRegistration(Base):
    """F-20: Employee self-registration via WhatsApp with admin approval."""
    __tablename__ = "pending_registrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    whatsapp_number: Mapped[str] = mapped_column(String(20), unique=True)
    department: Mapped[str] = mapped_column(String(100), default="Unassigned")
    role: Mapped[str] = mapped_column(String(100), default="Employee")
    status: Mapped[RegistrationStatus] = mapped_column(SAEnum(RegistrationStatus), default=RegistrationStatus.pending)
    reviewed_by: Mapped[str] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
