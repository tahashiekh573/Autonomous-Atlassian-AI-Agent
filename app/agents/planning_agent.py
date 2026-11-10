"""Planning Agent: turns an intent into an ordered, dependency-aware execution plan."""

import json
from datetime import UTC, datetime

from app.agents.base_agent import LLMAgent
from app.core.prompts import load_prompt
from app.schemas.agents import ExecutionPlan, PlanningInput


class PlanningAgent(LLMAgent[PlanningInput, ExecutionPlan]):
    name = "planning_agent"
    prompt_name = "planning_system"

    @property
    def system_prompt(self) -> str:
        # Each product agent owns a playbook describing how its operations should be planned.
        playbooks = ("jira_agent_system", "jsm_agent_system", "integration_agent_system")
        return "\n\n".join([load_prompt(self.prompt_name), *(load_prompt(p) for p in playbooks)])

    async def run(self, data: PlanningInput) -> ExecutionPlan:
        capabilities = json.dumps(data.capabilities, ensure_ascii=False)
        workspace = json.dumps(data.workspace, ensure_ascii=False)[:12000]
        prompt = (
            f"Today: {datetime.now(UTC).date().isoformat()}\n"
            f"Maximum operations: {data.max_operations}\n\n"
            f"## Request\n{data.intent.model_dump_json(indent=1)}\n\n"
            f"## Connected instance capabilities\n{capabilities}\n\n"
            f"## Existing resources (discovered)\n{workspace}\n\n"
            f"## Operation catalog\n{data.catalog}"
        )
        plan = await self._structured(prompt, ExecutionPlan)
        plan.operations = plan.operations[: data.max_operations]
        return plan
