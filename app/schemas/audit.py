"""API contracts for audit log entries."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    request_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    details: dict[str, Any]
