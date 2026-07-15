from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
import uuid


class TaskAttachment(Base):
    """One row per checklist item on a multi-attachment task.

    Pre-created `pending` when the task is generated; flipped to `received`
    (with the base64 image) as the employee sends each photo. base64 is nulled
    after the photo is forwarded to the admin — these rows are not an archive."""
    __tablename__ = "task_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    item_index: Mapped[int] = mapped_column(Integer)
    item_label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | received
    media_base64: Mapped[str] = mapped_column(Text, nullable=True)
    media_mimetype: Mapped[str] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    forwarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
