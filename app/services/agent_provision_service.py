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
from app.schemas.openclaw import AgentProvisionResult

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system"


class AgentProvisionClient(Protocol):
    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        ...


def sanitize_openclaw_error(exc: BaseException) -> str:
    if isinstance(exc, OpenClawTimeoutError):
        return "OpenClaw request timed out"
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

            if current_status == ProvisionStatus.READY:
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
        agent_id: str,
    ) -> UserAgent:
        try:
            user_agent = await self.repository.get_by_user_id_for_update(
                user_id,
            )
            if user_agent is None:
                raise ResourceNotFoundError(
                    code="user_agent_not_found",
                    message="User agent not found",
                )

            user_agent.agent_id = agent_id
            user_agent.provision_status = ProvisionStatus.READY.value
            user_agent.provision_error = None
            user_agent.updated_by = SYSTEM_ACTOR
            await self.db.commit()
            await self.db.refresh(user_agent)
            logger.info(
                "Agent provisioning succeeded, user_id=%s, agent_id=%s",
                user_id,
                agent_id,
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

    async def provision_for_user(
        self,
        *,
        user_id: int,
        manual_retry: bool = False,
    ) -> UserAgent:
        user_agent, should_provision = await self._mark_provisioning(
            user_id=user_id,
            manual_retry=manual_retry,
        )
        if not should_provision:
            return user_agent

        try:
            result = await self.openclaw_client.provision_agent(
                external_user_id=str(user_id),
            )
        except OpenClawError as exc:
            error_message = sanitize_openclaw_error(exc)
            return await self._finish_failure(
                user_id=user_id,
                error_message=error_message,
            )

        return await self._finish_success(
            user_id=user_id,
            agent_id=result.agent_id,
        )
