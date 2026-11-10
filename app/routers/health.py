"""Liveness and readiness probes (unauthenticated)."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import SQLAlchemyError

from app.core.dependencies import SettingsDep, get_database
from app.db.session import Database
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def liveness(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(status="ok", app=settings.app_name, environment=settings.environment)


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(
    settings: SettingsDep,
    database: Annotated[Database, Depends(get_database)],
    response: Response,
) -> HealthResponse:
    db_state: Literal["ok", "unavailable"] = "ok"
    try:
        await database.ping()
    except SQLAlchemyError:
        logger.exception("Database readiness check failed")
        db_state = "unavailable"
        response.status_code = 503
    return HealthResponse(
        status="ok" if db_state == "ok" else "degraded",
        app=settings.app_name,
        environment=settings.environment,
        database=db_state,
    )
