"""Response Agent: writes the human execution report from verified results.

Counts, statuses and resource IDs are computed from data; the LLM only writes the narrative,
so the report can never claim more than verification established.
"""

import logging

from pydantic import BaseModel, Field

from app.agents.base_agent import LLMAgent
from app.core.exceptions import LLMError
from app.core.prompts import load_prompt
from app.schemas.agents import ExecutionReport, ReportInput

logger = logging.getLogger(__name__)


class _Narrative(BaseModel):
    summary: str
    issues: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class ResponseAgent(LLMAgent[ReportInput, ExecutionReport]):
    name = "response_agent"
    prompt_name = "response_agent_system"

    @property
    def system_prompt(self) -> str:
        return load_prompt(self.prompt_name) + "\n\n" + load_prompt("verification_agent_system")

    async def run(self, data: ReportInput) -> ExecutionReport:
        ops = data.operations
        completed = [o for o in ops if o.status == "completed"]
        failed = [o for o in ops if o.status == "failed"]
        skipped = [o for o in ops if o.status == "skipped"]
        report = ExecutionReport(
            summary="",
            created_resources=[o.resource for o in completed if o.resource is not None],
            completed=len(completed),
            failed=len(failed),
            skipped=len(skipped),
            issues=[f"{o.op_id} {o.operation}: {o.message}" for o in [*failed, *skipped]],
        )
        try:
            narrative = await self._structured(
                f"Reply language: {data.language}\nOriginal request: {data.instruction}\n"
                f"Plan: {data.plan_summary}\n\nResults:\n"
                + "\n".join(o.model_dump_json(exclude_none=True) for o in ops),
                _Narrative,
            )
            report.summary = narrative.summary
            report.next_steps = narrative.next_steps
            if narrative.issues:
                report.issues = narrative.issues
        except LLMError as exc:
            logger.warning("Response agent fell back to a plain summary: %s", exc.message)
            report.summary = (
                f"{len(completed)} of {len(ops)} operation(s) completed and verified; "
                f"{len(failed)} failed, {len(skipped)} skipped."
            )
        return report
