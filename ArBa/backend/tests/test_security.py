from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api.deps import require_roles
from app.core.config import Settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.main import app


def test_password_hash_verifies_only_matching_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("incorrect password", password_hash)


def test_access_token_contains_user_subject_and_role() -> None:
    token = create_access_token(subject="42", role="PLANNER")

    claims = decode_access_token(token)

    assert claims["sub"] == "42"
    assert claims["role"] == "PLANNER"


def test_invalid_access_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token("not-a-valid-token")


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(app_env="production", jwt_secret="too-short")


def test_database_password_is_url_encoded() -> None:
    settings = Settings(db_host="db", db_password="secure:@/password")

    assert "secure%3A%40%2Fpassword" in settings.sqlalchemy_database_url


async def test_health_endpoint_is_available() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("user_role", "allowed_roles", "expected_status"),
    [
        ("PLANNER", ("PLANNER",), None),
        ("VIEWER", ("PLANNER",), 403),
        ("ADMIN", ("PLANNER",), None),
    ],
)
async def test_role_dependency(
    user_role: str,
    allowed_roles: tuple[str, ...],
    expected_status: int | None,
) -> None:
    dependency = require_roles(*allowed_roles)
    user = SimpleNamespace(role=user_role)

    if expected_status is None:
        assert await dependency(user=user) is user
    else:
        with pytest.raises(HTTPException) as error:
            await dependency(user=user)
        assert error.value.status_code == expected_status
