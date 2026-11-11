"""Pydantic contracts for every agent's input and output."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Language = Literal["en", "ur", "roman_ur", "mixed", "other"]
RiskClass = Literal["read", "create", "modify", "destructive", "security"]
OperationStatus = Literal[
    "pending", "requires_approval", "in_progress", "completed", "failed", "skipped"
]


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# --- Input Understanding ---------------------------------------------------------------------


class UnderstandingInput(BaseModel):
    text: str
    input_mode: Literal["text", "voice"] = "text"
    history: list[ConversationTurn] = Field(default_factory=list)


class Intent(BaseModel):
    language: Language = "en"
    normalized_instruction: str = Field(description="The request restated in clear English.")
    goals: list[str] = Field(default_factory=list)
    products: list[Literal["jira", "jsm", "confluence"]] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    is_actionable: bool = True
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)


# --- Planning --------------------------------------------------------------------------------


class PlanningInput(BaseModel):
    intent: Intent
    request_text: str = Field(
        default="", description="The user's original words (authoritative; the intent is a summary)"
    )
    catalog: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    workspace: dict[str, Any] = Field(default_factory=dict)
    max_operations: int = 40


class PlannedOperation(BaseModel):
    id: str = Field(pattern=r"^s\d{1,3}$", description="Step id: s1, s2, ...")
    operation: str
    description: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class CoverageItem(BaseModel):
    requirement: str = Field(description="One concrete item the user asked for")
    operation_ids: list[str] = Field(
        default_factory=list, description="Steps that deliver it (empty if not automatable)"
    )
    manual_reason: str | None = Field(
        default=None, description="Why it cannot be automated / what the user must do instead"
    )


class ExecutionPlan(BaseModel):
    summary: str
    operations: list[PlannedOperation] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(
        default_factory=list, description="Every requested item mapped to steps or a manual reason"
    )
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PlanExpansion(BaseModel):
    """Additional steps for requested items the current plan does not cover yet."""

    operations: list[PlannedOperation] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    complete: bool = Field(description="True when every requested item is now covered")


class PlanIssue(BaseModel):
    severity: Literal["error", "warning"]
    operation_id: str | None
    message: str


# --- Execution (Jira / JSM / Confluence / Integration agents) -------------------------------


class ResourceRef(BaseModel):
    type: str
    id: str | None = None
    key: str | None = None
    title: str | None = None
    url: str | None = None


class OperationRequest(BaseModel):
    run_id: str
    op_id: str
    operation: str
    params: dict[str, Any]
    mode: Literal["check", "execute"] = "execute"


class OperationOutcome(BaseModel):
    op_id: str
    operation: str
    agent: str
    succeeded: bool
    message: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    resource: ResourceRef | None = None
    reused_existing: bool = False
    conflict: bool = False
    notes: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)


# --- Verification ----------------------------------------------------------------------------


class VerificationRequest(BaseModel):
    operation: str
    params: dict[str, Any]
    outcome: OperationOutcome


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None


class VerificationResult(BaseModel):
    op_id: str
    verified: bool
    message: str
    checks: list[VerificationCheck] = Field(default_factory=list)


# --- Response --------------------------------------------------------------------------------


class OperationSummary(BaseModel):
    op_id: str
    operation: str
    description: str
    status: OperationStatus
    message: str
    resource: ResourceRef | None = None
    verified: bool | None = None


class ReportInput(BaseModel):
    instruction: str
    language: Language = "en"
    plan_summary: str
    operations: list[OperationSummary]


class ExecutionReport(BaseModel):
    summary: str
    created_resources: list[ResourceRef] = Field(default_factory=list)
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    issues: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
