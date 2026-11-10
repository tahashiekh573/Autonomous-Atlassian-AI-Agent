"""A saved Atlassian Cloud site + credentials."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AtlassianConnection(Base, TimestampMixin):
    __tablename__ = "atlassian_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    site_url: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    encrypted_api_token: Mapped[str] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_test_status: Mapped[str | None] = mapped_column(String(20), default=None)
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
