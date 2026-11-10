"""Persistence for Atlassian connections."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.atlassian_connection import AtlassianConnection


class ConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, connection: AtlassianConnection) -> AtlassianConnection:
        self._session.add(connection)
        await self._session.commit()
        await self._session.refresh(connection)
        return connection

    async def get(self, connection_id: str) -> AtlassianConnection | None:
        return await self._session.get(AtlassianConnection, connection_id)

    async def get_by_name(self, name: str) -> AtlassianConnection | None:
        result = await self._session.execute(
            select(AtlassianConnection).where(AtlassianConnection.name == name)
        )
        return result.scalar_one_or_none()

    async def list(self) -> Sequence[AtlassianConnection]:
        result = await self._session.execute(
            select(AtlassianConnection).order_by(AtlassianConnection.created_at)
        )
        return result.scalars().all()

    async def record_test_result(
        self,
        connection: AtlassianConnection,
        *,
        tested_at: datetime,
        status: str,
        capabilities: dict[str, Any],
    ) -> AtlassianConnection:
        connection.last_tested_at = tested_at
        connection.last_test_status = status
        connection.capabilities = capabilities
        await self._session.commit()
        await self._session.refresh(connection)
        return connection

    async def delete(self, connection: AtlassianConnection) -> None:
        await self._session.delete(connection)
        await self._session.commit()
