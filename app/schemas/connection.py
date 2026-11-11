"""API contracts for Atlassian connections."""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

Product = Literal["jira", "jsm", "confluence", "assets"]
TestStatus = Literal["ok", "partial", "failed"]


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    site_url: str = Field(description="e.g. https://your-site.atlassian.net")
    email: str = Field(max_length=255)
    api_token: SecretStr = Field(description="Atlassian API token (id.atlassian.com)")

    @field_validator("site_url")
    @classmethod
    def _normalise_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_RE.match(value):
            raise ValueError("must be a valid email address")
        return value

    @field_validator("api_token")
    @classmethod
    def _token_not_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be blank")
        return value


class ConnectionRead(BaseModel):
    """A saved connection. The API token is never returned."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    site_url: str
    email: str
    created_at: datetime
    last_tested_at: datetime | None
    last_test_status: TestStatus | None
    capabilities: dict[str, Any] | None


class AccountInfo(BaseModel):
    account_id: str
    display_name: str
    email_address: str | None


class ProductStatus(BaseModel):
    product: Product
    available: bool
    detail: str
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectionTestResult(BaseModel):
    connection_id: str
    status: TestStatus
    tested_at: datetime
    account: AccountInfo | None
    is_jira_admin: bool | None = Field(
        default=None, description="Global ADMINISTER permission; needed for most admin tasks."
    )
    products: list[ProductStatus]
