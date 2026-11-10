"""JSM Agent: executes Jira Service Management administration operations."""

from typing import ClassVar

from app.agents.handlers import jsm_handlers as h
from app.agents.handlers import jsm_reports
from app.agents.handlers.base import Handler
from app.agents.operation_agent import OperationAgent
from app.schemas.operations.spec import AgentName


class JsmAgent(OperationAgent):
    name = "jsm_agent"
    agent_name: ClassVar[AgentName] = "jsm"
    handlers: ClassVar[dict[str, Handler]] = {
        "jsm.list_service_desks": Handler(h.list_service_desks),
        "jsm.create_service_project": Handler(
            h.create_service_project, h.check_create_service_project
        ),
        "jsm.create_request_type": Handler(h.create_request_type),
        "jsm.list_request_types": Handler(h.list_request_types),
        "jsm.list_queues": Handler(h.list_queues),
        "jsm.create_organization": Handler(h.create_organization),
        "jsm.add_customers": Handler(h.add_customers),
        "jsm.create_request": Handler(h.create_request),
        "jsm.add_participants": Handler(h.add_participants),
        "jsm.sla_report": Handler(jsm_reports.sla_report),
        "jsm.request_report": Handler(jsm_reports.request_report),
    }
