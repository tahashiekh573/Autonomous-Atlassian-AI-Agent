"""Declarative description of one executable Atlassian operation."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agents import RiskClass

AgentName = Literal["jira", "jsm", "confluence", "integration"]

ProjectKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$", description="e.g. ITSD")]
SpaceKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,255}$", description="e.g. ITKB")]
IssueKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$", description="e.g. ITSD-12")]
IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")]


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoParams(Params):
    pass


class UnsupportedParams(BaseModel):
    """Free-form: the operation will not execute, details are only reported back."""

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class OperationSpec:
    name: str
    agent: AgentName
    risk: RiskClass
    description: str
    params: type[BaseModel]
    requires_products: tuple[str, ...] = ("jira",)
    needs_jira_admin: bool = False
    supported: bool = True
    limitation: str | None = None
    alternative: str | None = None
