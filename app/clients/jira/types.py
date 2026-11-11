"""Typed views of the Jira REST API v3 responses this client uses."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _JiraModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class JiraUser(_JiraModel):
    account_id: str = Field(alias="accountId")
    display_name: str = Field(alias="displayName")
    email_address: str | None = Field(default=None, alias="emailAddress")
    active: bool = True


class JiraServerInfo(_JiraModel):
    base_url: str = Field(alias="baseUrl")
    version: str | None = None
    deployment_type: str | None = Field(default=None, alias="deploymentType")
    server_title: str | None = Field(default=None, alias="serverTitle")


class JiraProject(_JiraModel):
    id: str
    key: str
    name: str
    project_type_key: str | None = Field(default=None, alias="projectTypeKey")
    style: str | None = None  # "classic" (company-managed) or "next-gen" (team-managed)
    issue_types: list[dict[str, Any]] = Field(default_factory=list, alias="issueTypes")
