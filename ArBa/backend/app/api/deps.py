from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import get_session
from app.models import AppUser, UserAssignment

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> AppUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid bearer token required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except (ValueError, KeyError, TypeError):
        raise unauthorized from None

    user = await session.scalar(select(AppUser).where(AppUser.id == user_id))
    if user is None or not user.active:
        raise unauthorized
    return user


def require_roles(*roles: str) -> Callable[..., Awaitable[AppUser]]:
    async def role_dependency(user: AppUser = Depends(get_current_user)) -> AppUser:
        if user.role != "ADMIN" and user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return role_dependency


async def ensure_customer_assignment(
    session: AsyncSession,
    user: AppUser,
    market_code: str,
    customer_id: int,
) -> None:
    if user.role == "ADMIN":
        return
    assignment = await session.scalar(
        select(UserAssignment).where(
            UserAssignment.user_id == user.id,
            UserAssignment.market_code == market_code,
            UserAssignment.customer_id == customer_id,
        )
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Plan account not assigned"
        )
