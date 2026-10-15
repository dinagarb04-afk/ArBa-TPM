from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)


class LifespanState(TypedDict):
    service: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[LifespanState]:
    logger.info("service_started", environment=settings.app_env)
    yield {"service": settings.app_name}
    logger.info("service_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "ArBa Trade Promotion Plan capability API. Dashboard records are "
        "synthetic development fixtures until domain services are implemented."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Content-Type", "X-Correlation-ID"],
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
