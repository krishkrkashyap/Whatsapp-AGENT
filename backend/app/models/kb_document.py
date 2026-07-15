from datetime import datetime, timezone
from sqlalchemy import String, Text, Enum as SAEnum
from sqlalchemy.orm import mapped_column, Mapped
from pgvector.sqlalchemy import Vector
from app.database import Base
import uuid
import enum

class SourceType(str, enum.Enum):
    pdf = "pdf"
    text = "text"
    url = "url"

class KBDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[SourceType] = mapped_column(SAEnum(SourceType))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Vector] = mapped_column(Vector(1536), nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="english")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
