"""Callbacks the orchestrators use to publish progress (implemented by the service layer)."""

from typing import Protocol

from app.schemas.agents import OperationOutcome, OperationStatus, VerificationResult


class RunEventSink(Protocol):
    async def run_progress(self, run_id: str, *, current_agent: str | None, message: str) -> None:
        """Which agent is working and what it is doing."""

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
        """An operation changed state."""


class NullSink:
    async def run_progress(self, run_id: str, *, current_agent: str | None, message: str) -> None:
        return None

    async def operation_status(
        self, run_id: str, op_id: str, status: OperationStatus, **_: object
    ) -> None:
        return None
