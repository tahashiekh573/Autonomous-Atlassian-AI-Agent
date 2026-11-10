"""HTTP endpoints for Atlassian connections. No business logic lives here."""

from typing import Any

from fastapi import APIRouter, status

from app.core.dependencies import AdminDep, ConnectionServiceDep, ViewerDep, WorkspaceServiceDep
from app.schemas.connection import ConnectionCreate, ConnectionRead, ConnectionTestResult

router = APIRouter(prefix="/connections", tags=["connections"])


@router.post("", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: ConnectionCreate, service: ConnectionServiceDep, _: AdminDep
) -> ConnectionRead:
    return await service.create(payload)


@router.get("", response_model=list[ConnectionRead])
async def list_connections(service: ConnectionServiceDep, _: ViewerDep) -> list[ConnectionRead]:
    return await service.list()


@router.get("/{connection_id}", response_model=ConnectionRead)
async def get_connection(
    connection_id: str, service: ConnectionServiceDep, _: ViewerDep
) -> ConnectionRead:
    return await service.get(connection_id)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: str, service: ConnectionServiceDep, _: AdminDep) -> None:
    await service.delete(connection_id)


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    connection_id: str, service: ConnectionServiceDep, _: AdminDep
) -> ConnectionTestResult:
    return await service.test(connection_id)


@router.get("/{connection_id}/overview")
async def connection_overview(
    connection_id: str, service: WorkspaceServiceDep, _: ViewerDep
) -> dict[str, Any]:
    return await service.overview(connection_id)
