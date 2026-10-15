from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.api.v1 import health
from app.main import app


async def request_health(path: str) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code


async def test_liveness_reports_service_status() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/health/live",
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_application_lifespan_starts_and_stops() -> None:
    async with app.router.lifespan_context(app) as state:
        assert state["service"] == "ArBa Trade Promotion Plan capability API"


async def test_readiness_reports_database_connectivity(monkeypatch) -> None:
    class ConnectionStub:
        async def __aenter__(self) -> ConnectionStub:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def execute(self, _statement: object) -> None:
            return None

    class EngineStub:
        def connect(self) -> ConnectionStub:
            return ConnectionStub()

    monkeypatch.setattr(health, "engine", EngineStub())

    assert await request_health("/api/v1/health/ready") == 200


async def test_readiness_fails_explicitly_when_database_is_unavailable(
    monkeypatch,
) -> None:
    class ConnectionFailure:
        def connect(self) -> ConnectionFailure:
            return self

        async def __aenter__(self) -> None:
            raise OperationalError("SELECT 1", {}, OSError("database unavailable"))

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(health, "engine", ConnectionFailure())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
