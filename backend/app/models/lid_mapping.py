"""Persistent LID-to-phone mapping table."""
from sqlalchemy import String, DateTime
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
from datetime import datetime, timezone


class LidMapping(Base):
    """Maps WhatsApp LID prefix (e.g. 87973831901323) to phone JID (e.g. 919876543210@c.us).
    
    This persists across restarts so fresh sessions don't need to re-resolve via contacts API.
    """
    __tablename__ = "lid_mappings"

    lid_prefix: Mapped[str] = mapped_column(String(32), primary_key=True)
    phone_jid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
