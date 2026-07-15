"""System-wide settings stored in DB (toggleable from admin dashboard)."""
from sqlalchemy import String, Text
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, nullable=True)
