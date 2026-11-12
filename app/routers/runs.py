"""Execution runs: submit a command, review the plan, approve, follow live status, history."""

from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.core.dependencies import OperatorDep, RunServiceDep, ViewerDep
from app.schemas.run import (
    ApproveRequest,
    ClarifyRequest,
    OperationCatalogEntry,
    RejectRequest,
    RunCreate,
    RunDetail,
    RunSummary,
)
from app.services.workspace_service import operation_catalog

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=RunDetail, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate,
    service: RunServiceDep,
    principal: OperatorDep,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> RunDetail:
    return await service.create(principal, payload, idempotency_key)


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    service: RunServiceDep,
    _: ViewerDep,
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[RunSummary]:
    return await service.list_recent(limit, status_filter)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, service: RunServiceDep, _: ViewerDep) -> RunDetail:
    return await service.get(run_id)


@router.post("/runs/{run_id}/approve", response_model=RunDetail)
async def approve_run(
    run_id: str, payload: ApproveRequest, service: RunServiceDep, principal: OperatorDep
) -> RunDetail:
    return await service.approve(principal, run_id, payload.operation_ids)


@router.post("/runs/{run_id}/reject", response_model=RunDetail)
async def reject_run(
    run_id: str, payload: RejectRequest, service: RunServiceDep, principal: OperatorDep
) -> RunDetail:
    return await service.reject(principal, run_id, payload.reason)


@router.post("/runs/{run_id}/stop", response_model=RunDetail)
async def stop_run(run_id: str, service: RunServiceDep, principal: OperatorDep) -> RunDetail:
    return await service.stop(principal, run_id)


@router.post("/runs/{run_id}/clarify", response_model=RunDetail)
async def clarify_run(
    run_id: str, payload: ClarifyRequest, service: RunServiceDep, principal: OperatorDep
) -> RunDetail:
    return await service.clarify(principal, run_id, payload.answer)


@router.get("/operations", response_model=list[OperationCatalogEntry])
async def list_operations(_: ViewerDep) -> list[OperationCatalogEntry]:
    return operation_catalog()
