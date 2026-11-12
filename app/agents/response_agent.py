"""Response Agent: writes the human execution report from verified results.

Counts, statuses and resource IDs are computed from data; the LLM only writes the narrative,
so the report can never claim more than verification established.
"""

import logging
from collections import Counter

from pydantic import BaseModel, Field

from app.agents.base_agent import LLMAgent
from app.agents.requirements import judge
from app.core.exceptions import LLMError
from app.core.prompts import load_prompt
from app.schemas.agents import ExecutionReport, OperationSummary, ReportInput

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
        # Counts always come from data: the model once reported "20 request types" for 16.
        facts = _facts(ops, completed, failed, skipped)
        report.requirements, report.completion_percent = judge(data.coverage, ops)
        if report.requirements:
            states = Counter(r.status for r in report.requirements)
            facts += (
                f" Requested items: {states['done']} of {len(report.requirements)} done"
                + (f", {states['partial']} partial" if states["partial"] else "")
                + (f", {states['failed']} failed" if states["failed"] else "")
                + (f", {states['missing']} not planned" if states["missing"] else "")
                + (f", {states['manual']} need manual setup" if states["manual"] else "")
                + (
                    f" ({report.completion_percent}% complete)."
                    if report.completion_percent is not None
                    else "."
                )
            )
            report.issues += [
                f"{r.requirement}: {r.status}" + (f" - {r.note}" if r.note else "")
                for r in report.requirements
                if r.status in ("failed", "missing", "partial")
            ]
        report.summary = facts
        try:
            narrative = await self._structured(
                f"Reply language: {data.language}\nOriginal request: {data.instruction}\n"
                f"Plan: {data.plan_summary}\n\nVerified facts (already shown to the user; do "
                f"not restate or change any number): {facts}\n\nResults:\n"
                + "\n".join(o.model_dump_json(exclude_none=True) for o in ops),
                _Narrative,
            )
            report.summary = f"{facts} {narrative.summary}".strip()
            report.next_steps = narrative.next_steps
        except LLMError as exc:
            logger.warning("Response agent fell back to a plain summary: %s", exc.message)
        return report


_READABLE = {
    "jsm.create_request_type": "request type",
    "jsm.create_form": "form",
    "jsm.create_service_project": "service project",
    "jira.create_project": "project",
    "jira.create_issue": "issue",
    "jsm.create_request": "request",
    "jira.create_workflow": "workflow",
    "jira.assign_workflow": "workflow assignment",
    "jira.create_filter": "filter",
    "jira.create_dashboard": "dashboard",
    "jira.create_automation_rule": "automation rule",
    "jira.create_priority": "priority",
    "jira.create_custom_field": "custom field",
    "confluence.create_space": "Confluence space",
    "confluence.create_page": "Confluence page",
}


def _plural(word: str, n: int) -> str:
    if n == 1:
        return word
    return word[:-1] + "ies" if word.endswith("y") else word + "s"


def _facts(
    ops: list[OperationSummary],
    completed: list[OperationSummary],
    failed: list[OperationSummary],
    skipped: list[OperationSummary],
) -> str:
    counts = Counter(o.operation for o in completed)
    parts = [
        f"{n} {_plural(_READABLE.get(op, op), n) if op in _READABLE else op}"
        for op, n in counts.most_common()
    ]
    text = f"{len(completed)} of {len(ops)} steps completed and verified"
    if parts:
        text += f" ({', '.join(parts)})"
    return f"{text}; {len(failed)} failed, {len(skipped)} skipped."
