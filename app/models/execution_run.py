"""One user instruction and everything that happened while executing it."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ExecutionRun(Base, TimestampMixin):
    __tablename__ = "execution_runs"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_run_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("atlassian_connections.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), default=None)
    input_mode: Mapped[str] = mapped_column(String(10), default="text")
    input_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)
    current_agent: Mapped[str | None] = mapped_column(String(50), default=None)
    progress_message: Mapped[str | None] = mapped_column(String(500), default=None)
    conversation: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    plan_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    approved_by: Mapped[str | None] = mapped_column(String(255), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    operations: Mapped[list["ExecutionOperation"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ExecutionOperation.position",
        lazy="selectin",
    )


class ExecutionOperation(Base, TimestampMixin):
    __tablename__ = "execution_operations"
    __table_args__ = (UniqueConstraint("run_id", "op_id", name="uq_run_op"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("execution_runs.id", ondelete="CASCADE")
    )
    op_id: Mapped[str] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(String(20))
    supported: Mapped[bool] = mapped_column(default=True)
    requires_approval: Mapped[bool] = mapped_column(default=False)
    approved: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text, default=None)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    preflight: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    run: Mapped[ExecutionRun] = relationship(back_populates="operations")
