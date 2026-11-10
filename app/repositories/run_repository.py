"""Persistence for execution runs and their operations."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_run import ExecutionOperation, ExecutionRun


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: ExecutionRun) -> ExecutionRun:
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def get(self, run_id: str) -> ExecutionRun | None:
        result = await self._session.execute(
            select(ExecutionRun)
            .where(ExecutionRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, created_by: str, key: str) -> ExecutionRun | None:
        result = await self._session.execute(
            select(ExecutionRun).where(
                ExecutionRun.created_by == created_by, ExecutionRun.idempotency_key == key
            )
        )
        return result.scalar_one_or_none()

    async def list_recent(
        self, limit: int, status: str | None = None, created_by: str | None = None
    ) -> Sequence[ExecutionRun]:
        query = select(ExecutionRun).order_by(ExecutionRun.created_at.desc()).limit(limit)
        if status:
            query = query.where(ExecutionRun.status == status)
        if created_by:
            query = query.where(ExecutionRun.created_by == created_by)
        return (await self._session.execute(query)).scalars().all()

    async def update_run(self, run_id: str, **values: Any) -> None:
        await self._session.execute(
            update(ExecutionRun).where(ExecutionRun.id == run_id).values(**values)
        )
        await self._session.commit()

    async def replace_operations(
        self, run: ExecutionRun, operations: list[ExecutionOperation]
    ) -> None:
        run.operations.clear()
        await self._session.flush()
        run.operations.extend(operations)
        await self._session.commit()

    async def update_operation(self, run_id: str, op_id: str, **values: Any) -> None:
        await self._session.execute(
            update(ExecutionOperation)
            .where(ExecutionOperation.run_id == run_id, ExecutionOperation.op_id == op_id)
            .values(**values)
        )
        await self._session.commit()

    async def mark_interrupted(self, statuses: list[str], message: str) -> int:
        result = await self._session.execute(
            update(ExecutionRun)
            .where(ExecutionRun.status.in_(statuses))
            .values(status="failed", error=message, current_agent=None)
        )
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def commit(self) -> None:
        await self._session.commit()
