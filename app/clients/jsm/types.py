"""Typed views of the Jira Service Management REST API responses this client uses."""

from pydantic import BaseModel, ConfigDict, Field


class _JsmModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class JsmInfo(_JsmModel):
    version: str | None = None
    platform_version: str | None = Field(default=None, alias="platformVersion")


class ServiceDesk(_JsmModel):
    id: str
    project_id: str = Field(alias="projectId")
    project_key: str = Field(alias="projectKey")
    project_name: str = Field(alias="projectName")
