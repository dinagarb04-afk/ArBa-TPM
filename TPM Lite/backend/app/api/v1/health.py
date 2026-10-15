from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import engine

router = APIRouter(tags=["health"])
logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]


@router.get("/health/live", response_model=HealthResponse, summary="Check API liveness")
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Check API and database readiness",
)
async def readiness() -> HealthResponse:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.error("readiness_check_failed", error_type=type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from error

    return HealthResponse(status="ready")
