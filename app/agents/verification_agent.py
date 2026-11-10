"""Verification Agent: re-reads the live instance and compares expected vs actual state."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.agents.base_agent import BaseAgent
from app.agents.handlers.base import HandlerContext
from app.agents.verifiers import jira_verifiers, other_verifiers
from app.agents.verifiers.base import Verifier
from app.core.exceptions import AppError
from app.schemas.agents import VerificationCheck, VerificationRequest, VerificationResult
from app.schemas.operations.catalog import get_spec

logger = logging.getLogger(__name__)

VERIFIERS: dict[str, Verifier] = {**jira_verifiers.VERIFIERS, **other_verifiers.VERIFIERS}


class VerificationAgent(BaseAgent[VerificationRequest, VerificationResult]):
    name = "verification_agent"

    def __init__(
        self,
        context: HandlerContext,
        retry_delay_seconds: float = 1.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._ctx = context
        self._retry_delay = retry_delay_seconds
        self._sleep = sleep

    async def run(self, data: VerificationRequest) -> VerificationResult:
        outcome = data.outcome
        if not outcome.succeeded:
            return VerificationResult(
                op_id=outcome.op_id,
                verified=False,
                message="Not verified: the operation did not succeed.",
            )
        spec = get_spec(data.operation)
        if spec is not None and spec.risk == "read":
            return VerificationResult(
                op_id=outcome.op_id,
                verified=True,
                message="Read-only operation; no state change to verify.",
            )
        verifier = VERIFIERS.get(data.operation)
        if verifier is None or spec is None:
            return VerificationResult(
                op_id=outcome.op_id,
                verified=False,
                message="No verifier exists for this operation.",
            )
        params = spec.params.model_validate(data.params)
        checks: list[VerificationCheck] = []
        error: str | None = None
        for attempt in range(2):  # one retry absorbs Atlassian's eventual consistency
            try:
                checks = await verifier(self._ctx, params, outcome)
                error = None
            except AppError as exc:
                checks, error = [], exc.message
            if checks and all(c.passed for c in checks):
                break
            if attempt == 0:
                await self._sleep(self._retry_delay)
        if error:
            return VerificationResult(
                op_id=outcome.op_id,
                verified=False,
                message=f"Verification could not read the resource: {error}",
            )
        failed = [c.name for c in checks if not c.passed]
        return VerificationResult(
            op_id=outcome.op_id,
            verified=not failed,
            checks=checks,
            message="Verified against live instance."
            if not failed
            else f"Mismatch on: {', '.join(failed)}.",
        )
