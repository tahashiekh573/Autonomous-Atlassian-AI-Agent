"""Step Repair Agent: fixes the parameters of one step that Jira rejected, then the step is retried.

Planning models make small, concrete mistakes (invented JQL functions, an issue type that is not
in the project, a status name with the wrong spelling). Jira's error message says exactly what
is wrong, so one focused call with that message usually yields a valid step - instead of a
skipped or failed item the user then has to do by hand.
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base_agent import LLMAgent
from app.schemas.operations.catalog import get_spec


class StepRepairInput(BaseModel):
    instruction: str = Field(description="The user's request (intent of the step)")
    operation: str
    description: str
    params: dict[str, Any]
    error: str
    facts: str = Field(default="", description="Site facts that may help (projects, types...)")


class StepRepair(BaseModel):
    fixable: bool = Field(description="False when the problem is not in the params")
    params: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


_SYSTEM = (
    "You repair ONE Atlassian Cloud administration step that Jira rejected. Keep the step's "
    "intent; change only what the error proves wrong. JQL must be valid Jira Cloud JQL: no "
    'invented functions (SLA fields use e.g. "Time to resolution" = breached() or '
    '< remaining("2h")), quote multi-word values with double quotes, use statuses and issue '
    "types that exist. Never change what the step is for: keep the target status, project, "
    "issue, space and every name the user gave. If a requested value does not exist, use only "
    "an equivalent with the same meaning (e.g. the workflow's final DONE status 'Completed' for "
    "'Resolved'); never a different stage. If there is no equivalent, or the error is not caused "
    "by the params (permissions, missing licence, the target already exists), answer "
    "fixable=false. Reply with JSON only."
)


class StepRepairAgent(LLMAgent[StepRepairInput, StepRepair]):
    name = "step_repair_agent"

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    async def run(self, data: StepRepairInput) -> StepRepair:
        spec = get_spec(data.operation)
        schema = (
            json.dumps(spec.params.model_json_schema(), ensure_ascii=False)[:3000] if spec else ""
        )
        return await self._structured(
            f"## User request\n{data.instruction[:4000]}\n\n## Step\n{data.operation}: "
            f"{data.description}\nparams: {json.dumps(data.params, ensure_ascii=False)}\n"
            f"params schema: {schema}\n\n## Jira's error\n{data.error}\n\n"
            + (f"## Site facts\n{data.facts[:3000]}\n\n" if data.facts else "")
            + "## Task\nReturn corrected params (complete object, valid for the schema).",
            StepRepair,
        )
