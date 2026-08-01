import logging
from dataclasses import dataclass
from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.errors import AuthenticationError, ResourceConflictError
from app.core.provisioning import ProvisionStatus
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.snowflake import SnowflakeGenerator, get_snowflake_generator
from app.models.user import User
from app.models.user_agent import UserAgent
from app.repository.user_agent_repository import UserAgentRepository
from app.repository.user_repository import UserRepository
from app.services.agent_provision_service import (
    AgentProvisionClient,
    AgentProvisioningService,
)
from app.schemas.auth import UserLoginRequest, UserRegisterRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    expires_in: int
    user: User


@dataclass(frozen=True, slots=True)
class RegisterResult:
    user: User
    user_agent: UserAgent


class AuthService:
    """用户注册、登录与 Access Token 业务编排。"""

    def __init__(
        self,
        db: AsyncSession,
        repository: UserRepository | None = None,
        user_agent_repository: UserAgentRepository | None = None,
        snowflake_generator: SnowflakeGenerator | None = None,
        openclaw_client: AgentProvisionClient | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or UserRepository(db)
        self.user_agent_repository = (
            user_agent_repository or UserAgentRepository(db)
        )
        self.snowflake_generator = (
            snowflake_generator or get_snowflake_generator()
        )
        self.openclaw_client = openclaw_client

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().lower()

    @staticmethod
    def _normalize_phone(phone: str | None) -> str | None:
        return phone.strip() if phone is not None else None

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        return email.strip().lower() if email is not None else None

    @staticmethod
    def _normalize_display_name(display_name: str) -> str:
        return display_name.strip()

    async def _ensure_registration_identity_available(
        self,
        *,
        username: str,
        phone: str | None,
    ) -> None:
        logger.debug(
            "注册前校验身份唯一性开始，username=%s, phone_present=%s",
            username,
            phone is not None,
        )
        if await self.repository.get_by_username(
            username,
            include_deleted=True,
        ) is not None:
            raise ResourceConflictError(
                code="username_conflict",
                message="用户名已存在",
            )

        if (
            phone is not None
            and await self.repository.get_by_phone(
                phone,
                include_deleted=True,
            )
            is not None
        ):
            raise ResourceConflictError(
                code="phone_conflict",
                message="手机号已存在",
            )
        logger.debug("注册前校验身份唯一性完成，username=%s", username)

    async def _raise_registration_conflict(
        self,
        exc: IntegrityError,
        *,
        username: str,
        phone: str | None,
    ) -> NoReturn:
        if await self.repository.get_by_username(
            username,
            include_deleted=True,
        ) is not None:
            raise ResourceConflictError(
                code="username_conflict",
                message="用户名已存在",
            ) from exc

        if (
            phone is not None
            and await self.repository.get_by_phone(
                phone,
                include_deleted=True,
            )
            is not None
        ):
            raise ResourceConflictError(
                code="phone_conflict",
                message="手机号已存在",
            ) from exc

        raise ResourceConflictError(
            code="user_conflict",
            message="用户名或手机号已存在",
        ) from exc

    async def register(self, request: UserRegisterRequest) -> RegisterResult:
        username = self._normalize_username(request.username)
        phone = self._normalize_phone(request.phone)
        email = self._normalize_email(
            str(request.email) if request.email is not None else None
        )
        logger.debug(
            "注册流程开始，username=%s, email_present=%s, phone_present=%s",
            username,
            email is not None,
            phone is not None,
        )
        await self._ensure_registration_identity_available(
            username=username,
            phone=phone,
        )

        logger.debug("注册流程准备生成密码哈希，username=%s", username)
        password_hash = await run_in_threadpool(
            hash_password,
            request.password,
        )
        user_id = self.snowflake_generator.next_id()
        logger.debug(
            "注册流程已生成用户ID，username=%s, user_id=%s",
            username,
            user_id,
        )
        user = User(
            id=user_id,
            username=username,
            password_hash=password_hash,
            display_name=self._normalize_display_name(
                request.display_name
            ),
            phone=phone,
            email=email,
            is_deleted=False,
            created_by=username,
            updated_by=username,
        )
        try:
            logger.debug(
                "注册流程准备写入用户和默认Agent绑定，user_id=%s",
                user_id,
            )
            await self.repository.create(user)
            user_agent = UserAgent(
                user_id=user.id,
                agent_id=None,
                provision_status=ProvisionStatus.PENDING.value,
                is_deleted=False,
            )
            await self.user_agent_repository.create(user_agent)
            await self.db.commit()
            await self.db.refresh(user)
            logger.debug(
                "注册流程数据库写入完成，user_id=%s, user_agent_id=%s",
                user.id,
                user_agent.id,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            logger.debug("注册流程数据库唯一性冲突，username=%s", username)
            await self._raise_registration_conflict(
                exc,
                username=username,
                phone=phone,
            )
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

        if self.openclaw_client is None:
            logger.debug(
                "注册流程未配置OpenClaw客户端，跳过Agent创建，user_id=%s",
                user.id,
            )
            return RegisterResult(user=user, user_agent=user_agent)

        logger.debug("注册流程准备调用Agent创建服务，user_id=%s", user.id)
        provisioned_user_agent = await AgentProvisioningService(
            self.db,
            self.openclaw_client,
        ).provision_for_user(user_id=user.id)
        logger.debug(
            "注册流程Agent创建服务调用完成，user_id=%s, provision_status=%s",
            user.id,
            provisioned_user_agent.provision_status,
        )

        return RegisterResult(user=user, user_agent=provisioned_user_agent)

    async def authenticate(
        self,
        account: str,
        password: str,
    ) -> User | None:
        normalized_account = account.strip().lower()
        logger.debug(
            "登录认证开始，account_length=%s",
            len(normalized_account),
        )
        user = await self.repository.get_by_login_account(
            normalized_account
        )
        if user is None:
            logger.debug("登录认证未找到用户，account_length=%s", len(normalized_account))
            return None
        password_is_valid = await run_in_threadpool(
            verify_password,
            password,
            user.password_hash,
        )
        if not password_is_valid:
            logger.debug("登录认证密码校验失败，user_id=%s", user.id)
            return None
        logger.debug("登录认证成功，user_id=%s", user.id)
        return user

    async def login(self, request: UserLoginRequest) -> LoginResult:
        logger.debug(
            "登录流程开始，account_length=%s",
            len(request.account),
        )
        user = await self.authenticate(
            request.account,
            request.password,
        )
        if user is None:
            logger.debug("登录流程失败，account_length=%s", len(request.account))
            raise AuthenticationError(
                code="invalid_credentials",
                message="账号或密码错误",
            )

        logger.debug("登录流程准备生成Access Token，user_id=%s", user.id)
        access_token, expires_in = create_access_token(
            user.id,
            user.username,
        )
        logger.debug(
            "登录流程Access Token生成完成，user_id=%s, expires_in=%s",
            user.id,
            expires_in,
        )
        return LoginResult(
            access_token=access_token,
            expires_in=expires_in,
            user=user,
        )
