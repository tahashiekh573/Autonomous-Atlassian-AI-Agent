"""Integration Agent: connects Jira, JSM and Confluence resources and keeps references intact."""

from typing import ClassVar

from app.agents.handlers import integration_handlers as h
from app.agents.handlers.base import Handler
from app.agents.operation_agent import OperationAgent
from app.schemas.operations.spec import AgentName


class IntegrationAgent(OperationAgent):
    name = "integration_agent"
    agent_name: ClassVar[AgentName] = "integration"
    handlers: ClassVar[dict[str, Handler]] = {
        "integration.link_issue_to_page": Handler(h.link_issue_to_page),
        "integration.link_incident_to_issue": Handler(h.link_incident_to_issue),
        "integration.create_dev_issue_from_incident": Handler(h.create_dev_issue_from_incident),
        "integration.embed_issues_in_page": Handler(h.embed_issues_in_page),
        "integration.link_project_to_space": Handler(h.link_project_to_space),
    }
