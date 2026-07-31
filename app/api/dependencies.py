from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openclaw_client import OpenClawClient
from app.core.database import get_db
from app.core.errors import AuthenticationError
from app.core.snowflake import get_snowflake_generator
from app.core.settings import settings
from app.core.security import TokenValidationError, decode_access_token
from app.models.user import User
from app.repository.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.user_agent_service import UserAgentService
from app.services.user_service import UserService

DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


async def get_auth_service(db: DatabaseDependency) -> AuthService:
    return AuthService(db, snowflake_generator=get_snowflake_generator())


AuthServiceDependency = Annotated[
    AuthService,
    Depends(get_auth_service),
]


async def get_user_service(db: DatabaseDependency) -> UserService:
    return UserService(db, snowflake_generator=get_snowflake_generator())


UserServiceDependency = Annotated[
    UserService,
    Depends(get_user_service),
]


async def get_user_agent_service(
    db: DatabaseDependency,
) -> UserAgentService:
    return UserAgentService(db)


UserAgentServiceDependency = Annotated[
    UserAgentService,
    Depends(get_user_agent_service),
]


def get_openclaw_client() -> OpenClawClient:
    return OpenClawClient(
        base_url=settings.openclaw_base_url,
        gateway_token=settings.openclaw_gateway_token.get_secret_value(),
        timeout_seconds=settings.openclaw_timeout_seconds,
    )


OpenClawClientDependency = Annotated[
    OpenClawClient,
    Depends(get_openclaw_client),
]


def _invalid_authentication_error() -> AuthenticationError:
    return AuthenticationError(
        code="invalid_token",
        message="认证凭证无效",
    )


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: DatabaseDependency,
) -> User:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
    ):
        raise _invalid_authentication_error()

    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
        if (
            not isinstance(subject, str)
            or not subject.isdecimal()
            or subject.startswith("0")
        ):
            raise ValueError
        user_id = int(subject)
        if user_id <= 0:
            raise ValueError
    except (TokenValidationError, TypeError, ValueError):
        raise _invalid_authentication_error() from None

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise _invalid_authentication_error()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

__all__ = [
    "AuthServiceDependency",
    "CurrentUser",
    "DatabaseDependency",
    "OpenClawClientDependency",
    "UserAgentServiceDependency",
    "UserServiceDependency",
    "get_openclaw_client",
]
