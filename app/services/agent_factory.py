"""Assembles the agents for one run (dependency injection for the orchestrators)."""

from collections.abc import Callable

from app.agents.confluence_agent import ConfluenceAgent, LLMContentWriter
from app.agents.handlers.base import HandlerContext
from app.agents.input_understanding_agent import InputUnderstandingAgent
from app.agents.integration_agent import IntegrationAgent
from app.agents.jira_agent import JiraAgent
from app.agents.jsm_agent import JsmAgent
from app.agents.planning_agent import PlanningAgent
from app.agents.response_agent import ResponseAgent
from app.agents.verification_agent import VerificationAgent
from app.clients.atlassian.factory import AtlassianClients
from app.clients.llm.base import LLMClient
from app.orchestrators.agent_set import AgentSet

AgentSetBuilder = Callable[[AtlassianClients, str, str | None, LLMClient, float], AgentSet]


def build_agent_set(
    clients: AtlassianClients,
    site_url: str,
    account_id: str | None,
    llm: LLMClient,
    verification_retry_delay: float,
) -> AgentSet:
    context = HandlerContext(
        clients=clients,
        site_url=site_url,
        run_id="",
        op_id="",
        account_id=account_id,
        content_writer=LLMContentWriter(llm),
    )
    return AgentSet(
        understanding=InputUnderstandingAgent(llm),
        planning=PlanningAgent(llm),
        jira=JiraAgent(context),
        jsm=JsmAgent(context),
        confluence=ConfluenceAgent(context),
        integration=IntegrationAgent(context),
        verification=VerificationAgent(context, retry_delay_seconds=verification_retry_delay),
        response=ResponseAgent(llm),
    )
