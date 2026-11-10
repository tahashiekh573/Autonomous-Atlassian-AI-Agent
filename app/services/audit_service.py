"""Records consequential actions in the audit trail."""

from typing import Any

from app.core.logging import request_id_ctx
from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.audit import AuditLogRead


class AuditService:
    def __init__(self, repository: AuditLogRepository, actor: str = "admin") -> None:
        self._repo = repository
        self._actor = actor

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._repo.add(
            AuditLog(
                request_id=request_id_ctx.get(),
                actor=self._actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                details=details or {},
            )
        )

    async def list_recent(self, limit: int) -> list[AuditLogRead]:
        return [AuditLogRead.model_validate(e) for e in await self._repo.list_recent(limit)]
