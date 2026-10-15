from datetime import UTC, datetime, timedelta
from typing import Any, cast

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

password_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return cast(str, password_context.hash(password))


def verify_password(password: str, password_hash: str) -> bool:
    return cast(bool, password_context.verify(password, password_hash))


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    claims: dict[str, Any] = {"sub": subject, "role": role, "exp": expires_at}
    return cast(
        str,
        jwt.encode(
            claims,
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        ),
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return cast(
            dict[str, Any],
            jwt.decode(
                token,
                settings.jwt_secret.get_secret_value(),
                algorithms=[settings.jwt_algorithm],
            ),
        )
    except JWTError as exc:
        raise ValueError("Invalid or expired access token") from exc
