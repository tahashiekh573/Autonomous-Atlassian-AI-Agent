"""Shared types for operation handlers (the deterministic tool layer used by execution agents)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from app.clients.atlassian.factory import AtlassianClients
from app.clients.confluence.confluence_client import ConfluenceClient
from app.clients.jira.jira_client import JiraClient
from app.clients.jsm.assets_client import AssetsClient
from app.clients.jsm.forms_client import FormsClient
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
    def forms(self) -> FormsClient:
        return self.clients.forms

    @property
    def assets(self) -> AssetsClient:
        return self.clients.assets

    def workflow_name(self, name: str) -> str:
        """The name a workflow requested as `name` actually got in this run.

        When a different workflow already owns the requested name, the new one is created as
        "Name 2" (never silently reusing a workflow with other statuses); later steps that refer
        to it by the requested name are pointed at the new one.
        """
        aliases: dict[str, str] = self.cache.get("workflow_alias", {})
        return aliases.get(name.casefold(), name)

    def alias_workflow(self, requested: str, actual: str) -> None:
        self.cache.setdefault("workflow_alias", {})[requested.casefold()] = actual

    @property
    def idempotency_label(self) -> str:
        """Stable per (run, step): lets a retried step find what it already created.

        Stored only in an invisible issue property (never a label, name or description), so
        nothing the agent builds carries an "AI agent" marker.
        """
        return f"run-{self.run_id.replace('-', '')[:8]}-{self.op_id}"


STEP_PROPERTY = "automation.step"


def free_name(base: str, taken: list[str]) -> str:
    """`base`, or `base 2`, `base 3`, ... - the first name not already used (case-insensitive)."""
    used = {t.strip().casefold() for t in taken}
    if base.casefold() not in used:
        return base
    n = 2
    while f"{base} {n}".casefold() in used:
        n += 1
    return f"{base} {n}"


def step_marker(ctx: HandlerContext) -> list[dict[str, Any]]:
    """`properties` for POST /issue: tags the new issue with this step, invisibly."""
    return [{"key": STEP_PROPERTY, "value": {"step": ctx.idempotency_label}}]


async def mark_issue(ctx: HandlerContext, key: str) -> None:
    await ctx.jira.set_issue_property(key, STEP_PROPERTY, {"step": ctx.idempotency_label})


async def find_step_issue(
    ctx: HandlerContext, project_key: str, summary: str
) -> dict[str, Any] | None:
    """The issue this step already created (on retry), matched by summary and step property."""
    recent = await ctx.jira.search(
        f'project = "{project_key}" AND creator = currentUser() AND created >= -2d '
        "ORDER BY created DESC",
        fields=["summary"],
        max_results=50,
    )
    wanted = summary.strip().casefold()
    for issue in recent:
        if str((issue.get("fields") or {}).get("summary") or "").strip().casefold() != wanted:
            continue
        value = await ctx.jira.get_issue_property(str(issue["key"]), STEP_PROPERTY)
        if isinstance(value, dict) and value.get("step") == ctx.idempotency_label:
            return issue
    return None


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
