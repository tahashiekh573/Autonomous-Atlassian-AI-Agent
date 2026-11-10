"""Read-only access to the audit trail."""

from fastapi import APIRouter, Query

from app.core.dependencies import AdminDep, AuditServiceDep
from app.schemas.audit import AuditLogRead

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogRead])
async def list_audit_logs(
    service: AuditServiceDep, _: AdminDep, limit: int = Query(default=50, ge=1, le=500)
) -> list[AuditLogRead]:
    return await service.list_recent(limit)
