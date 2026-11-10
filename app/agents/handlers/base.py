"""Shared types for operation handlers (the deterministic tool layer used by execution agents)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from app.clients.atlassian.factory import AtlassianClients
from app.clients.confluence.confluence_client import ConfluenceClient
from app.clients.jira.jira_client import JiraClient
from app.clients.jsm.jsm_client import JsmClient
from app.schemas.agents import ResourceRef


class ContentWriter(Protocol):
    async def write(self, *, page_kind: str, title: str, brief: str, existing: str = "") -> str:
        """Return Confluence storage-format XHTML for the page."""


@dataclass
class HandlerContext:
    clients: AtlassianClients
    site_url: str
    run_id: str
    op_id: str
    account_id: str | None = None
    content_writer: ContentWriter | None = None
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def jira(self) -> JiraClient:
        return self.clients.jira

    @property
    def jsm(self) -> JsmClient:
        return self.clients.jsm

    @property
    def confluence(self) -> ConfluenceClient:
        return self.clients.confluence

    @property
    def idempotency_label(self) -> str:
        """Stable per (run, step): lets a retried step find what it already created."""
        return f"aiagent-{self.run_id.replace('-', '')[:8]}-{self.op_id}"


@dataclass
class HandlerResult:
    message: str
    outputs: dict[str, Any] = field(default_factory=dict)
    resource: ResourceRef | None = None
    reused_existing: bool = False


@dataclass
class CheckResult:
    """Read-only preflight finding for one planned operation."""

    notes: list[str] = field(default_factory=list)
    conflict: bool = False


Execute = Callable[[HandlerContext, Any], Awaitable[HandlerResult]]
Check = Callable[[HandlerContext, Any], Awaitable[CheckResult]]


@dataclass(frozen=True)
class Handler:
    execute: Execute
    check: Check | None = None


def same_name(a: str | None, b: str | None) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_none=True)
