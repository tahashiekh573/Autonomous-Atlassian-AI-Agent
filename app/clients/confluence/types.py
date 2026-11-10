"""Typed views of the Confluence REST API v2 responses this client uses."""

from pydantic import BaseModel, ConfigDict


class ConfluenceSpace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    key: str
    name: str
    type: str | None = None
    status: str | None = None
