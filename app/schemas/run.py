"""API contracts for execution runs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal[
    "planning",
    "needs_clarification",
    "blocked",
    "awaiting_approval",
    "executing",
    "completed",
    "completed_with_errors",
    "failed",
    "rejected",
]
ACTIVE_STATUSES = ("planning", "executing")

# Long, structured "master prompts" are a normal way to describe a whole environment.
MAX_COMMAND_CHARS = 50_000


class RunCreate(BaseModel):
    connection_id: str
    text: str = Field(min_length=1, max_length=MAX_COMMAND_CHARS)
    input_mode: Literal["text", "voice"] = "text"


class ApproveRequest(BaseModel):
    operation_ids: list[str] | None = Field(
        default=None,
        description="Steps to approve. Omit to approve every step except destructive and "
        "security-sensitive ones, which must always be listed explicitly.",
    )


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class ClarifyRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=MAX_COMMAND_CHARS)


class OperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    op_id: str
    position: int
    operation: str
    agent: str
    description: str
    risk: str
    supported: bool
    requires_approval: bool
    approved: bool
    status: str
    message: str | None
    params: dict[str, Any]
    resolved_params: dict[str, Any] | None
    depends_on: list[str]
    preflight: dict[str, Any] | None
    outcome: dict[str, Any] | None
    verification: dict[str, Any] | None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    created_by: str
    input_mode: str
    input_text: str
    status: RunStatus
    current_agent: str | None
    progress_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class RunDetail(RunSummary):
    conversation: list[dict[str, Any]]
    intent: dict[str, Any] | None
    plan: dict[str, Any] | None
    plan_issues: list[dict[str, Any]]
    report: dict[str, Any] | None
    error: str | None
    approved_by: str | None
    approved_at: datetime | None
    operations: list[OperationRead]


class OperationCatalogEntry(BaseModel):
    name: str
    agent: str
    risk: str
    description: str
    supported: bool
    needs_jira_admin: bool
    limitation: str | None
    alternative: str | None
    params_schema: dict[str, Any]
