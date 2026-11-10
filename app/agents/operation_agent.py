"""Common execution logic for the Jira, JSM, Confluence and Integration agents."""

import logging
from typing import ClassVar

from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.agents.handlers.base import Handler, HandlerContext
from app.core.exceptions import AppError
from app.schemas.agents import OperationOutcome, OperationRequest
from app.schemas.operations.catalog import get_spec
from app.schemas.operations.spec import AgentName

logger = logging.getLogger(__name__)


class OperationAgent(BaseAgent[OperationRequest, OperationOutcome]):
    """Validates parameters, then runs (or preflight-checks) one catalog operation."""

    agent_name: ClassVar[AgentName]
    handlers: ClassVar[dict[str, Handler]]

    def __init__(self, context: HandlerContext) -> None:
        self._base_context = context

    async def run(self, data: OperationRequest) -> OperationOutcome:
        spec = get_spec(data.operation)
        if spec is None or spec.agent != self.agent_name:
            return self._fail(data, f"{self.name} cannot handle '{data.operation}'.", "unknown_op")
        if not spec.supported:
            return self._fail(
                data,
                f"Not supported by the Atlassian public API: {spec.limitation} "
                f"Alternative: {spec.alternative}",
                "operation_unsupported",
            )
        handler = self.handlers.get(data.operation)
        if handler is None:
            return self._fail(
                data, f"{self.name} has no handler for '{data.operation}'.", "unknown_op"
            )
        try:
            params = spec.params.model_validate(data.params)
        except ValidationError as exc:
            errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return self._fail(data, f"Invalid parameters: {errors}", "operation_invalid_input")

        ctx = HandlerContext(
            clients=self._base_context.clients,
            site_url=self._base_context.site_url,
            run_id=data.run_id,
            op_id=data.op_id,
            account_id=self._base_context.account_id,
            content_writer=self._base_context.content_writer,
            cache=self._base_context.cache,
        )
        try:
            if data.mode == "check":
                if handler.check is None:
                    return OperationOutcome(
                        op_id=data.op_id,
                        operation=data.operation,
                        agent=self.name,
                        succeeded=True,
                        message="No preflight check needed.",
                    )
                check = await handler.check(ctx, params)
                return OperationOutcome(
                    op_id=data.op_id,
                    operation=data.operation,
                    agent=self.name,
                    succeeded=not check.conflict,
                    conflict=check.conflict,
                    notes=check.notes,
                    message="; ".join(check.notes) or "Preflight check passed.",
                )
            result = await handler.execute(ctx, params)
        except AppError as exc:
            logger.info("%s %s failed: %s", self.name, data.operation, exc.message)
            return self._fail(data, exc.message, exc.code, exc.details)
        return OperationOutcome(
            op_id=data.op_id,
            operation=data.operation,
            agent=self.name,
            succeeded=True,
            message=result.message,
            outputs=result.outputs,
            resource=result.resource,
            reused_existing=result.reused_existing,
        )

    def _fail(
        self,
        data: OperationRequest,
        message: str,
        code: str,
        details: dict[str, object] | None = None,
    ) -> OperationOutcome:
        return OperationOutcome(
            op_id=data.op_id,
            operation=data.operation,
            agent=self.name,
            succeeded=False,
            message=message,
            error_code=code,
            error_details=dict(details or {}),
        )
