"""Persistence for audit log entries."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: AuditLog) -> AuditLog:
        self._session.add(entry)
        await self._session.commit()
        return entry

    async def list_recent(self, limit: int = 50) -> Sequence[AuditLog]:
        result = await self._session.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        )
        return result.scalars().all()
