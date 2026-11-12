"""The set of agents an orchestrator coordinates for one run."""

from dataclasses import dataclass

from app.agents.base_agent import BaseAgent
from app.agents.step_repair_agent import StepRepair, StepRepairInput
from app.agents.verification_agent import VerificationAgent
from app.schemas.agents import (
    ExecutionPlan,
    ExecutionReport,
    Intent,
    OperationOutcome,
    OperationRequest,
    PlanningInput,
    ReportInput,
    UnderstandingInput,
)
from app.schemas.operations.catalog import get_spec

OperationAgentT = BaseAgent[OperationRequest, OperationOutcome]


@dataclass
class AgentSet:
    understanding: BaseAgent[UnderstandingInput, Intent]
    planning: BaseAgent[PlanningInput, ExecutionPlan]
    jira: OperationAgentT
    jsm: OperationAgentT
    confluence: OperationAgentT
    integration: OperationAgentT
    verification: VerificationAgent
    response: BaseAgent[ReportInput, ExecutionReport]
    # Fixes a rejected step's params once (optional so tests can run without an LLM).
    repair: BaseAgent[StepRepairInput, StepRepair] | None = None

    def for_operation(self, operation: str) -> OperationAgentT:
        spec = get_spec(operation)
        if spec is None:
            raise KeyError(operation)
        agent: OperationAgentT = getattr(self, spec.agent)
        return agent
