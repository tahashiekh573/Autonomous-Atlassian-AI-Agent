"""Confluence Agent: executes Confluence operations and writes page content with the LLM."""

from typing import ClassVar

from app.agents.handlers import confluence_handlers as h
from app.agents.handlers.base import Handler
from app.agents.operation_agent import OperationAgent
from app.clients.llm.base import LLMClient
from app.core.prompts import load_prompt
from app.schemas.operations.spec import AgentName


class ConfluenceAgent(OperationAgent):
    name = "confluence_agent"
    agent_name: ClassVar[AgentName] = "confluence"
    handlers: ClassVar[dict[str, Handler]] = {
        "confluence.list_spaces": Handler(h.list_spaces),
        "confluence.create_space": Handler(h.create_space, h.check_create_space),
        "confluence.update_space": Handler(h.update_space),
        "confluence.create_page": Handler(h.create_page),
        "confluence.update_page": Handler(h.update_page),
        "confluence.add_labels": Handler(h.add_labels),
        "confluence.create_index_page": Handler(h.create_index_page),
        "confluence.set_space_permission": Handler(h.set_space_permission),
        "confluence.delete_page": Handler(h.delete_page, h.check_delete_page),
    }


class LLMContentWriter:
    """Writes Confluence storage-format XHTML for a page from a brief."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def write(self, *, page_kind: str, title: str, brief: str, existing: str = "") -> str:
        prompt = f"Page type: {page_kind}\nTitle: {title}\nBrief:\n{brief or title}\n" + (
            f"\nCurrent page content to revise:\n{existing[:20000]}\n" if existing else ""
        )
        text = await self._llm.generate(
            system=load_prompt("confluence_agent_system"), prompt=prompt, json_mode=False
        )
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        return text.strip()
