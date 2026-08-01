import logging
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    OpenClawAuthenticationError,
    OpenClawConfigurationError,
    OpenClawConflictError,
    OpenClawConnectionError,
    OpenClawError,
    OpenClawRequestError,
    OpenClawResponseError,
    OpenClawTimeoutError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.core.provisioning import ProvisionStatus
from app.models.user_agent import UserAgent
from app.repository.user_agent_repository import UserAgentRepository
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
)

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system"


class AgentProvisionClient(Protocol):
    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        ...

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        ...


def sanitize_openclaw_error(exc: BaseException) -> str:
    if isinstance(exc, OpenClawTimeoutError):
        return "Backend timed out while waiting for OpenClaw"
    if isinstance(exc, OpenClawConnectionError):
        return "OpenClaw connection failed"
    if isinstance(exc, OpenClawAuthenticationError):
        return "OpenClaw authentication failed"
    if isinstance(exc, OpenClawConflictError):
        return "OpenClaw agent conflict"
    if isinstance(exc, OpenClawRequestError):
        return "OpenClaw rejected provisioning request"
    if isinstance(exc, OpenClawResponseError):
        return "OpenClaw returned invalid response"
    if isinstance(exc, OpenClawConfigurationError):
        return "OpenClaw client configuration invalid"
    return "OpenClaw provisioning failed"


class AgentProvisioningService:
    def __init__(
        self,
        db: AsyncSession,
        openclaw_client: AgentProvisionClient,
        repository: UserAgentRepository | None = None,
    ) -> None:
        self.db = db
        self.openclaw_client = openclaw_client
        self.repository = repository or UserAgentRepository(db)

    @staticmethod
    def _status(value: str) -> ProvisionStatus:
        if value == "creating":
            return ProvisionStatus.PENDING
        return ProvisionStatus(value)

    async def _mark_provisioning(
        self,
        *,
        user_id: int,
        manual_retry: bool,
    ) -> tuple[UserAgent, bool]:
        try:
            logger.debug(
                "Agent创建流程准备锁定用户Agent记录，user_id=%s, "
                "manual_retry=%s",
                user_id,
                manual_retry,
            )
            user_agent = await self.repository.get_by_user_id_for_update(
                user_id,
            )
            if user_agent is None:
                await self.db.rollback()
                raise ResourceNotFoundError(
                    code="user_agent_not_found",
                    message="User agent not found",
                )

            current_status = self._status(user_agent.provision_status)
            logger.info(
                "Agent provisioning requested, user_id=%s, status=%s, "
                "manual_retry=%s",
                user_id,
                current_status.value,
                manual_retry,
            )

            if current_status in (
                ProvisionStatus.REGISTERED,
                ProvisionStatus.WARMING,
                ProvisionStatus.READY,
            ):
                logger.debug(
                    "Agent创建流程无需重复创建，user_id=%s, status=%s",
                    user_id,
                    current_status.value,
                )
                await self.db.commit()
                return user_agent, False

            if current_status == ProvisionStatus.PROVISIONING:
                logger.info(
                    "Duplicate Agent provisioning rejected, user_id=%s",
                    user_id,
                )
                await self.db.rollback()
                raise ResourceConflictError(
                    code="agent_provisioning_in_progress",
                    message=(
                        "Agent provisioning is already in progress, "
                        "please do not submit repeatedly"
                    ),
                )

            user_agent.provision_status = ProvisionStatus.PROVISIONING.value
            user_agent.provision_error = None
            user_agent.updated_by = SYSTEM_ACTOR
            await self.db.commit()
            logger.debug(
                "Agent创建流程已标记为创建中，user_id=%s",
                user_id,
            )
            return user_agent, True
        except (ResourceConflictError, ResourceNotFoundError):
            raise
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

    async def _finish_success(
        self,
        *,
        user_id: int,
        result: AgentProvisionResult,
        readiness: AgentRuntimeEnsureReadyResult | None,
    ) -> UserAgent:
        try:
            logger.debug(
                "Agent创建成功收尾开始，user_id=%s, agent_id=%s",
                user_id,
                result.agent_id,
            )
            user_agent = await self.repository.get_by_user_id_for_update(
                user_id,
            )
            if user_agent is None:
                raise ResourceNotFoundError(
                    code="user_agent_not_found",
                    message="User agent not found",
                )

            user_agent.agent_id = result.agent_id
            status_value = result.provision_status
            provision_error = None
            if readiness is not None:
                if readiness.ready:
                    status_value = ProvisionStatus.READY
                else:
                    status_value = self._readiness_status(
                        readiness.reason or readiness.error,
                    )
                    provision_error = (
                        readiness.reason
                        or readiness.error
                        or "runtime_owner_not_ready"
                    )
            user_agent.provision_status = status_value.value
            user_agent.provision_error = provision_error
            user_agent.updated_by = SYSTEM_ACTOR
            await self.db.commit()
            await self.db.refresh(user_agent)
            logger.debug(
                "Agent创建成功收尾完成，user_id=%s, status=%s",
                user_id,
                user_agent.provision_status,
            )
            logger.info(
                "Agent provisioning succeeded, user_id=%s, agent_id=%s, "
                "status=%s, agent_ready=%s",
                user_id,
                result.agent_id,
                user_agent.provision_status,
                result.agent_ready,
            )
            return user_agent
        except IntegrityError:
            if self.db.in_transaction():
                await self.db.rollback()
            raise ResourceConflictError(
                code="agent_id_conflict",
                message="Agent ID already exists",
            ) from None
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

    async def _finish_failure(
        self,
        *,
        user_id: int,
        error_message: str,
    ) -> UserAgent:
        try:
            logger.debug(
                "Agent创建失败收尾开始，user_id=%s",
                user_id,
            )
            user_agent = await self.repository.get_by_user_id_for_update(
                user_id,
            )
            if user_agent is None:
                raise ResourceNotFoundError(
                    code="user_agent_not_found",
                    message="User agent not found",
                )

            user_agent.agent_id = None
            user_agent.provision_status = ProvisionStatus.FAILED.value
            user_agent.provision_error = error_message
            user_agent.updated_by = SYSTEM_ACTOR
            await self.db.commit()
            await self.db.refresh(user_agent)
            logger.debug(
                "Agent创建失败收尾完成，user_id=%s",
                user_id,
            )
            logger.info(
                "Agent provisioning failed, user_id=%s, error_type=%s",
                user_id,
                error_message,
            )
            return user_agent
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

    @staticmethod
    def _readiness_status(value: str | None) -> ProvisionStatus:
        if value is None:
            return ProvisionStatus.WARMING
        try:
            status_value = ProvisionStatus(value)
        except ValueError:
            return ProvisionStatus.WARMING
        if status_value == ProvisionStatus.READY:
            return ProvisionStatus.READY
        if status_value in (
            ProvisionStatus.REGISTERED,
            ProvisionStatus.WARMING,
        ):
            return status_value
        return ProvisionStatus.WARMING

    async def _warm_up_runtime(
        self,
        *,
        user_id: int,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult | None:
        try:
            logger.debug(
                "Agent运行时预热检查开始，user_id=%s, agent_id=%s",
                user_id,
                agent_id,
            )
            readiness = await self.openclaw_client.ensure_agent_runtime_ready(
                agent_id=agent_id,
            )
        except OpenClawError as exc:
            logger.warning(
                "OpenClaw Agent runtime warm-up failed after provisioning, "
                "user_id=%s, agent_id=%s, error_type=%s",
                user_id,
                agent_id,
                type(exc).__name__,
            )
            return None
        logger.debug(
            "Agent运行时预热检查完成，user_id=%s, agent_id=%s, ready=%s",
            user_id,
            agent_id,
            readiness.ready,
        )
        logger.info(
            "OpenClaw Agent runtime warm-up checked after provisioning, "
            "user_id=%s, agent_id=%s, ready=%s, refreshed=%s, reason=%s, "
            "error=%s",
            user_id,
            agent_id,
            readiness.ready,
            readiness.refreshed,
            readiness.reason,
            readiness.error,
        )
        return readiness

    async def provision_for_user(
        self,
        *,
        user_id: int,
        manual_retry: bool = False,
    ) -> UserAgent:
        logger.debug(
            "Agent创建流程开始，user_id=%s, manual_retry=%s",
            user_id,
            manual_retry,
        )
        user_agent, should_provision = await self._mark_provisioning(
            user_id=user_id,
            manual_retry=manual_retry,
        )
        if not should_provision:
            logger.debug(
                "Agent创建流程结束，使用现有记录，user_id=%s, status=%s",
                user_id,
                user_agent.provision_status,
            )
            return user_agent

        try:
            logger.debug("准备调用OpenClaw创建Agent，user_id=%s", user_id)
            result = await self.openclaw_client.provision_agent(
                external_user_id=str(user_id),
            )
            logger.debug(
                "OpenClaw创建Agent调用完成，user_id=%s, agent_id=%s",
                user_id,
                result.agent_id,
            )
        except OpenClawError as exc:
            error_message = sanitize_openclaw_error(exc)
            logger.debug(
                "OpenClaw创建Agent调用失败，user_id=%s, error_type=%s",
                user_id,
                type(exc).__name__,
            )
            return await self._finish_failure(
                user_id=user_id,
                error_message=error_message,
            )

        readiness = await self._warm_up_runtime(
            user_id=user_id,
            agent_id=result.agent_id,
        )
        return await self._finish_success(
            user_id=user_id,
            result=result,
            readiness=readiness,
        )
