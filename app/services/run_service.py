"""Request-facing business logic for execution runs: create, approve, reject, clarify."""

from app.core.exceptions import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    RequestValidationAppError,
)
from app.db.base import utcnow
from app.models.execution_run import ExecutionRun
from app.orchestrators.approval_policy import ELEVATED_RISKS, required_role
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.run_repository import RunRepository
from app.schemas.auth import Principal
from app.schemas.run import ACTIVE_STATUSES, RunCreate, RunDetail, RunSummary
from app.services.audit_service import AuditService
from app.services.run_engine import RunEngine

_REVISABLE = ("needs_clarification", "blocked", "awaiting_approval")


class RunService:
    def __init__(
        self,
        runs: RunRepository,
        connections: ConnectionRepository,
        audit: AuditService,
        engine: RunEngine,
    ) -> None:
        self._runs = runs
        self._connections = connections
        self._audit = audit
        self._engine = engine

    async def create(
        self, principal: Principal, data: RunCreate, idempotency_key: str | None = None
    ) -> RunDetail:
        if idempotency_key:
            existing = await self._runs.get_by_idempotency_key(principal.email, idempotency_key)
            if existing:
                return RunDetail.model_validate(existing)
        connection = await self._connections.get(data.connection_id)
        if connection is None:
            raise NotFoundError(f"Connection '{data.connection_id}' not found.")
        if not connection.capabilities or connection.last_test_status == "failed":
            raise RequestValidationAppError(
                "Test the Atlassian connection successfully before running commands "
                "(POST /api/v1/connections/{id}/test)."
            )
        if not self._engine.llm_available:
            raise ConfigurationError("No LLM is configured (set GEMINI_API_KEY or OPENAI_API_KEY).")
        run = await self._runs.add(
            ExecutionRun(
                connection_id=data.connection_id,
                created_by=principal.email,
                idempotency_key=idempotency_key,
                input_mode=data.input_mode,
                input_text=data.text,
                status="planning",
                progress_message="Queued",
                conversation=[{"role": "user", "content": data.text}],
            )
        )
        await self._audit.record(
            action="run.create",
            resource_type="execution_run",
            resource_id=run.id,
            outcome="accepted",
            details={"input_mode": data.input_mode},
        )
        self._engine.start_planning(run.id)
        return RunDetail.model_validate(await self._require(run.id))

    async def get(self, run_id: str) -> RunDetail:
        return RunDetail.model_validate(await self._require(run_id))

    async def list_recent(self, limit: int, status: str | None) -> list[RunSummary]:
        return [RunSummary.model_validate(r) for r in await self._runs.list_recent(limit, status)]

    async def approve(
        self, principal: Principal, run_id: str, operation_ids: list[str] | None
    ) -> RunDetail:
        run = await self._require(run_id)
        if run.status != "awaiting_approval":
            raise ConflictError(f"Run is '{run.status}', not awaiting approval.")
        pending = {o.op_id: o for o in run.operations if o.requires_approval}
        if operation_ids is None:
            selected = {i for i, o in pending.items() if o.risk not in ELEVATED_RISKS}
        else:
            unknown = set(operation_ids) - pending.keys()
            if unknown:
                raise RequestValidationAppError(
                    f"Not awaiting approval: {', '.join(sorted(unknown))}."
                )
            selected = set(operation_ids)
        if pending and not selected:
            raise RequestValidationAppError(
                "Nothing selected. Destructive and security-sensitive steps must be approved by "
                "listing their ids in operation_ids; use reject to cancel the run."
            )
        for op_id in selected:
            role = required_role(pending[op_id].risk)  # type: ignore[arg-type]
            if not principal.has_role(role):
                raise AuthorizationError(
                    f"Step {op_id} is {pending[op_id].risk}; it needs approval by an {role}."
                )
        for op in run.operations:
            if op.op_id in selected:
                op.approved = True
                op.status = "pending"
        run.status = "executing"
        run.approved_by = principal.email
        run.approved_at = utcnow()
        run.progress_message = "Approved; executing"
        await self._runs.commit()
        await self._audit.record(
            action="run.approve",
            resource_type="execution_run",
            resource_id=run_id,
            outcome="approved",
            details={
                "approved": sorted(selected),
                "not_approved": sorted(pending.keys() - selected),
            },
        )
        self._engine.start_execution(run_id)
        return await self.get(run_id)

    async def reject(self, principal: Principal, run_id: str, reason: str) -> RunDetail:
        run = await self._require(run_id)
        if run.status not in _REVISABLE:
            raise ConflictError(f"Run is '{run.status}' and cannot be rejected.")
        for op in run.operations:
            op.status = "skipped"
            op.message = "Plan rejected."
        run.status = "rejected"
        run.error = reason or None
        run.finished_at = utcnow()
        await self._runs.commit()
        await self._audit.record(
            action="run.reject",
            resource_type="execution_run",
            resource_id=run_id,
            outcome="rejected",
            details={"reason": reason},
        )
        return await self.get(run_id)

    async def clarify(self, principal: Principal, run_id: str, answer: str) -> RunDetail:
        """Answer clarification questions or request plan changes; the run is re-planned."""
        run = await self._require(run_id)
        if run.status not in _REVISABLE:
            raise ConflictError(f"Run is '{run.status}'; it can no longer be revised.")
        if self._engine.tasks.is_running(run_id) or run.status in ACTIVE_STATUSES:
            raise ConflictError("The run is busy.")
        run.conversation = [*run.conversation, {"role": "user", "content": answer}]
        run.status = "planning"
        run.progress_message = "Re-planning with your answer"
        await self._runs.commit()
        await self._audit.record(
            action="run.clarify",
            resource_type="execution_run",
            resource_id=run_id,
            outcome="accepted",
        )
        self._engine.start_planning(run_id)
        return await self.get(run_id)

    async def _require(self, run_id: str) -> ExecutionRun:
        run = await self._runs.get(run_id)
        if run is None:
            raise NotFoundError(f"Run '{run_id}' not found.")
        return run
