"""Jira Agent: executes Jira Software administration operations."""

from typing import ClassVar

from app.agents.handlers import (
    jira_agile,
    jira_automation,
    jira_config,
    jira_dashboards,
    jira_issues,
    jira_projects,
    jira_reports,
    jira_team_workflows,
    jira_transition_tour,
    jira_workflow_schemes,
    jira_workflows,
)
from app.agents.handlers.base import Handler
from app.agents.operation_agent import OperationAgent
from app.schemas.operations.spec import AgentName


class JiraAgent(OperationAgent):
    name = "jira_agent"
    agent_name: ClassVar[AgentName] = "jira"
    handlers: ClassVar[dict[str, Handler]] = {
        "jira.whoami": Handler(jira_projects.whoami),
        "jira.list_projects": Handler(jira_projects.list_projects),
        "jira.create_project": Handler(
            jira_projects.create_project, jira_projects.check_create_project
        ),
        "jira.update_project": Handler(jira_projects.update_project),
        "jira.create_issue_type": Handler(jira_config.create_issue_type),
        "jira.configure_issue_types": Handler(
            jira_config.configure_issue_types, jira_config.check_configure_issue_types
        ),
        "jira.create_custom_field": Handler(jira_config.create_custom_field),
        "jira.create_screen": Handler(jira_config.create_screen),
        "jira.add_field_to_screen": Handler(jira_config.add_field_to_screen),
        "jira.create_field_configuration": Handler(jira_config.create_field_configuration),
        "jira.create_priority": Handler(jira_config.create_priority),
        "jira.create_statuses": Handler(jira_config.create_statuses),
        "jira.create_workflow": Handler(
            jira_workflows.create_workflow, jira_workflows.check_create_workflow
        ),
        "jira.assign_workflow": Handler(jira_workflows.assign_workflow),
        "jira.configure_workflow_scheme": Handler(jira_workflow_schemes.configure_workflow_scheme),
        "jira.update_workflow": Handler(jira_workflow_schemes.update_workflow),
        "jira.set_issue_type_workflow": Handler(
            jira_team_workflows.set_issue_type_workflow,
            jira_team_workflows.check_set_issue_type_workflow,
        ),
        "jira.create_issue": Handler(jira_issues.create_issue, jira_issues.check_create_issue),
        "jira.update_issue": Handler(jira_issues.update_issue),
        "jira.transition_issue": Handler(jira_issues.transition_issue),
        "jira.verify_workflow_transitions": Handler(
            jira_transition_tour.verify_workflow_transitions
        ),
        "jira.link_issues": Handler(jira_issues.link_issues),
        "jira.delete_issue": Handler(jira_issues.delete_issue, jira_issues.check_delete_issue),
        "jira.search_issues": Handler(jira_issues.search_issues),
        "jira.create_filter": Handler(jira_agile.create_filter, jira_agile.check_create_filter),
        "jira.create_board": Handler(jira_agile.create_board),
        "jira.create_sprint": Handler(jira_agile.create_sprint),
        "jira.start_sprint": Handler(jira_agile.start_sprint),
        "jira.move_issues_to_sprint": Handler(jira_agile.move_issues_to_sprint),
        "jira.move_issues_to_backlog": Handler(jira_agile.move_issues_to_backlog),
        "jira.create_dashboard": Handler(jira_dashboards.create_dashboard),
        "jira.generate_report": Handler(jira_reports.generate_report),
        "jira.create_automation_rule": Handler(
            jira_automation.create_automation_rule, jira_automation.check_automation_rule
        ),
    }
