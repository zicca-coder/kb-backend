from typing import Annotated, AsyncIterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openclaw_client import OpenClawClient
from app.core.database import get_db
from app.core.errors import AuthenticationError, OpenClawConfigurationError
from app.core.snowflake import get_snowflake_generator
from app.core.settings import settings
from app.core.security import TokenValidationError, decode_access_token
from app.models.user import User
from app.repository.user_repository import UserRepository
from app.services.agent_provision_service import (
    AgentProvisionClient,
    AgentProvisioningService,
)
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.user_agent_service import UserAgentService
from app.services.user_service import UserService
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
    OpenClawChatResult,
)

DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
bearer_scheme = HTTPBearer(auto_error=False)


class UnavailableOpenClawClient:
    def __init__(self, message: str) -> None:
        self.message = message

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        raise OpenClawConfigurationError(self.message)

    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
    ) -> OpenClawChatResult:
        raise OpenClawConfigurationError(self.message)

    async def stream_chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
    ) -> AsyncIterator[str]:
        raise OpenClawConfigurationError(self.message)
        yield

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        raise OpenClawConfigurationError(self.message)


def get_openclaw_client() -> AgentProvisionClient:
    try:
        return OpenClawClient(
            base_url=settings.openclaw_base_url,
            gateway_token=settings.openclaw_gateway_token.get_secret_value(),
            connect_timeout_seconds=(
                settings.openclaw_connect_timeout_seconds
            ),
            read_timeout_seconds=settings.openclaw_read_timeout_seconds,
            write_timeout_seconds=settings.openclaw_write_timeout_seconds,
            pool_timeout_seconds=settings.openclaw_pool_timeout_seconds,
        )
    except OpenClawConfigurationError as exc:
        return UnavailableOpenClawClient(str(exc))


OpenClawClientDependency = Annotated[
    AgentProvisionClient,
    Depends(get_openclaw_client),
]


async def get_auth_service(
    db: DatabaseDependency,
    openclaw_client: OpenClawClientDependency,
) -> AuthService:
    return AuthService(
        db,
        snowflake_generator=get_snowflake_generator(),
        openclaw_client=openclaw_client,
    )


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


async def get_agent_provisioning_service(
    db: DatabaseDependency,
    openclaw_client: OpenClawClientDependency,
) -> AgentProvisioningService:
    return AgentProvisioningService(db, openclaw_client)


AgentProvisioningServiceDependency = Annotated[
    AgentProvisioningService,
    Depends(get_agent_provisioning_service),
]


async def get_chat_service(
    db: DatabaseDependency,
    openclaw_client: OpenClawClientDependency,
) -> ChatService:
    return ChatService(db, openclaw_client)


ChatServiceDependency = Annotated[
    ChatService,
    Depends(get_chat_service),
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
    "ChatServiceDependency",
    "CurrentUser",
    "DatabaseDependency",
    "AgentProvisioningServiceDependency",
    "OpenClawClientDependency",
    "UserAgentServiceDependency",
    "UserServiceDependency",
    "get_openclaw_client",
]
