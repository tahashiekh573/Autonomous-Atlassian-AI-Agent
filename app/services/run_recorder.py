"""Persists orchestrator progress events (live status for the dashboard + audit trail)."""

from typing import Any

from app.core.logging import request_id_ctx
from app.db.session import Database
from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.run_repository import RunRepository
from app.schemas.agents import OperationOutcome, OperationStatus, VerificationResult


class RunRecorder:
    def __init__(self, database: Database, actor: str) -> None:
        self._db = database
        self._actor = actor

    async def run_progress(self, run_id: str, *, current_agent: str | None, message: str) -> None:
        async with self._db.session() as session:
            await RunRepository(session).update_run(
                run_id, current_agent=current_agent, progress_message=message[:500]
            )

    async def operation_status(
        self,
        run_id: str,
        op_id: str,
        status: OperationStatus,
        *,
        message: str = "",
        agent: str | None = None,
        resolved_params: dict[str, object] | None = None,
        outcome: OperationOutcome | None = None,
        verification: VerificationResult | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status, "message": message}
        if agent:
            values["agent"] = agent
        if resolved_params is not None:
            values["resolved_params"] = resolved_params
        if outcome is not None:
            values["outcome"] = outcome.model_dump(mode="json")
        if verification is not None:
            values["verification"] = verification.model_dump(mode="json")
        async with self._db.session() as session:
            await RunRepository(session).update_operation(run_id, op_id, **values)
            if status in ("completed", "failed"):
                resource = outcome.resource if outcome else None
                await AuditLogRepository(session).add(
                    AuditLog(
                        request_id=request_id_ctx.get(),
                        actor=self._actor,
                        action=f"operation.{status}",
                        resource_type="execution_operation",
                        resource_id=f"{run_id}:{op_id}",
                        outcome=status,
                        details={
                            "operation": outcome.operation if outcome else None,
                            "resource": resource.model_dump(exclude_none=True)
                            if resource
                            else None,
                            "verified": verification.verified if verification else None,
                            "message": message[:500],
                        },
                    )
                )
