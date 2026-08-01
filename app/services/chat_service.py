import logging
from dataclasses import dataclass
from time import perf_counter
from typing import AsyncIterator, Protocol
from uuid import uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversations import ConversationMessageStatus
from app.core.errors import (
    AppError,
    OpenClawAuthenticationError,
    OpenClawConfigurationError,
    OpenClawConflictError,
    OpenClawConnectionError,
    OpenClawError,
    OpenClawRequestError,
    OpenClawResponseError,
    OpenClawRuntimeNotReadyError,
    OpenClawTimeoutError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.core.provisioning import (
    DEFAULT_AGENT_RETRY_AFTER_MS,
    ProvisionStatus,
)
from app.repository.conversation_repository import ConversationRepository
from app.repository.user_agent_repository import UserAgentRepository
from app.schemas.openclaw import (
    AgentRuntimeEnsureReadyResult,
    OpenClawChatResult,
)
from app.services.conversation_service import ConversationService

logger = logging.getLogger("uvicorn.error")
CHAT_ANSWER_LOG_PREVIEW_CHARS = 2000


class ChatClient(Protocol):
    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
    ) -> OpenClawChatResult:
        ...

    async def stream_chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
    ) -> AsyncIterator[str]:
        ...

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        ...


@dataclass(frozen=True, slots=True)
class ChatResult:
    answer: str


@dataclass(frozen=True, slots=True)
class PreparedChatRequest:
    user_id: int
    agent_id: str
    openclaw_user: str
    message: str
    session_key: str
    conversation_id: str | None = None
    assistant_message_id: int | None = None


class ChatService:
    def __init__(
        self,
        db: AsyncSession,
        openclaw_client: ChatClient,
        repository: UserAgentRepository | None = None,
        conversation_service: ConversationService | None = None,
    ) -> None:
        self.db = db
        self.openclaw_client = openclaw_client
        self.repository = repository or UserAgentRepository(db)
        self.conversation_service = (
            conversation_service
            or ConversationService(
                db,
                repository=ConversationRepository(db),
            )
        )

    async def prepare_chat_for_user(
        self,
        *,
        user_id: int,
        message: str,
        conversation_id: str | None = None,
        request_id: str | None = None,
    ) -> PreparedChatRequest:
        logger.debug(
            "聊天请求准备开始，user_id=%s, message_length=%s",
            user_id,
            len(message),
        )
        user_agent = await self.repository.get_by_user_id(user_id)
        if user_agent is None:
            logger.debug("聊天请求准备失败，用户未绑定Agent，user_id=%s", user_id)
            raise ResourceNotFoundError(
                code="user_agent_not_found",
                message="当前用户 Agent 绑定不存在",
            )

        try:
            provision_status = ProvisionStatus(user_agent.provision_status)
        except ValueError as exc:
            logger.error(
                "Invalid UserAgent provision_status, user_id=%s, "
                "user_agent_id=%s",
                user_id,
                user_agent.id,
            )
            raise AppError(
                code="agent_state_invalid",
                message="Agent 数据状态异常",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        agent_id = user_agent.agent_id.strip() if user_agent.agent_id else ""
        logger.debug(
            "聊天请求读取到Agent绑定，user_id=%s, user_agent_id=%s, "
            "provision_status=%s, agent_id_present=%s",
            user_id,
            user_agent.id,
            provision_status.value,
            bool(agent_id),
        )

        if provision_status == ProvisionStatus.PENDING:
            logger.debug("聊天请求准备失败，Agent尚未创建，user_id=%s", user_id)
            raise ResourceConflictError(
                code="agent_not_ready",
                message="Agent 尚未创建完成",
            )
        if provision_status == ProvisionStatus.PROVISIONING:
            logger.debug("聊天请求准备失败，Agent创建中，user_id=%s", user_id)
            raise ResourceConflictError(
                code="agent_provisioning",
                message="Agent 正在创建中，请稍后重试",
            )
        if provision_status == ProvisionStatus.FAILED:
            logger.debug("聊天请求准备失败，Agent创建失败，user_id=%s", user_id)
            raise ResourceConflictError(
                code="agent_provision_failed",
                message="Agent 创建失败，请先重新创建 Agent",
            )

        if not agent_id:
            logger.error(
                "Ready UserAgent has no agent_id, user_id=%s, "
                "user_agent_id=%s",
                user_id,
                user_agent.id,
            )
            raise AppError(
                code="agent_state_invalid",
                message="Agent 数据状态异常",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if provision_status != ProvisionStatus.READY:
            logger.debug(
                "聊天请求准备调用Agent运行时就绪检查，user_id=%s, "
                "agent_id=%s, provision_status=%s",
                user_id,
                agent_id,
                provision_status.value,
            )
            await self._ensure_agent_ready(
                user_id=user_id,
                agent_id=agent_id,
            )

        assistant_message_id: int | None = None
        if conversation_id is not None:
            pair = await self.conversation_service.create_chat_message_pair(
                user_id=user_id,
                conversation_id=conversation_id,
                user_content=message,
                request_id=request_id,
                assistant_status=(
                    ConversationMessageStatus.STREAMING
                    if request_id is not None
                    else ConversationMessageStatus.PENDING
                ),
            )
            assistant_message_id = pair.assistant_message.id

        logger.debug(
            "聊天请求准备完成，user_id=%s, agent_id=%s",
            user_id,
            agent_id,
        )
        return PreparedChatRequest(
            user_id=user_id,
            agent_id=agent_id,
            openclaw_user=str(user_id),
            message=message,
            session_key=self._chat_session_key(
                conversation_id=conversation_id,
                request_id=request_id,
            ),
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
        )

    async def chat_for_user(
        self,
        *,
        user_id: int,
        message: str,
        conversation_id: str | None = None,
    ) -> ChatResult:
        prepared = await self.prepare_chat_for_user(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
        )

        logger.info(
            "OpenClaw chat requested, user_id=%s, agent_id=%s, "
            "message_length=%s",
            user_id,
            prepared.agent_id,
            len(message),
        )
        started_at = perf_counter()
        try:
            logger.debug(
                "同步聊天准备调用OpenClaw，user_id=%s, agent_id=%s",
                user_id,
                prepared.agent_id,
            )
            result = await self.openclaw_client.chat_completion(
                agent_id=prepared.agent_id,
                openclaw_user=prepared.openclaw_user,
                message=prepared.message,
                session_key=prepared.session_key,
            )
        except OpenClawRuntimeNotReadyError as exc:
            await self._finalize_prepared_error(
                prepared=prepared,
                error_message="agent_runtime_not_ready",
            )
            await self._mark_runtime_not_ready(user_id=user_id)
            raise AppError(
                code="agent_runtime_not_ready",
                message="Agent runtime is not ready yet, please retry later",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={
                    "agent_id": prepared.agent_id,
                    "provision_status": ProvisionStatus.WARMING.value,
                    "retry_after_ms": DEFAULT_AGENT_RETRY_AFTER_MS,
                },
            ) from exc
        except OpenClawError as exc:
            mapped = self._map_openclaw_error(
                exc,
                agent_id=prepared.agent_id,
            )
            await self._finalize_prepared_error(
                prepared=prepared,
                error_message=f"{mapped.code}: {mapped.message}",
            )
            raise mapped from exc

        await self._finalize_prepared_completed(
            prepared=prepared,
            answer=result.answer,
        )
        logger.info(
            "OpenClaw chat response, user_id=%s, agent_id=%s, "
            "elapsed_ms=%s, answer_length=%s, answer_preview=%r",
            user_id,
            prepared.agent_id,
            round((perf_counter() - started_at) * 1000),
            len(result.answer),
            result.answer[:CHAT_ANSWER_LOG_PREVIEW_CHARS],
        )
        logger.debug(
            "同步聊天OpenClaw调用完成，user_id=%s, agent_id=%s, "
            "answer_length=%s",
            user_id,
            prepared.agent_id,
            len(result.answer),
        )
        return ChatResult(answer=result.answer)

    async def stream_prepared_chat(
        self,
        *,
        prepared: PreparedChatRequest,
    ) -> AsyncIterator[str]:
        logger.info(
            "OpenClaw stream chat requested, user_id=%s, agent_id=%s, "
            "message_length=%s",
            prepared.user_id,
            prepared.agent_id,
            len(prepared.message),
        )
        try:
            logger.debug(
                "流式聊天准备调用OpenClaw，user_id=%s, agent_id=%s",
                prepared.user_id,
                prepared.agent_id,
            )
            async for delta in self.openclaw_client.stream_chat_completion(
                agent_id=prepared.agent_id,
                openclaw_user=prepared.openclaw_user,
                message=prepared.message,
                session_key=prepared.session_key,
            ):
                logger.debug(
                    "流式聊天收到OpenClaw增量，user_id=%s, agent_id=%s, "
                    "delta_length=%s",
                    prepared.user_id,
                    prepared.agent_id,
                    len(delta),
                )
                yield delta
        except OpenClawRuntimeNotReadyError as exc:
            await self._mark_runtime_not_ready(user_id=prepared.user_id)
            raise AppError(
                code="agent_runtime_not_ready",
                message="Agent runtime is not ready yet, please retry later",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={
                    "agent_id": prepared.agent_id,
                    "provision_status": ProvisionStatus.WARMING.value,
                    "retry_after_ms": DEFAULT_AGENT_RETRY_AFTER_MS,
                },
            ) from exc
        except OpenClawError as exc:
            mapped = self._map_openclaw_error(
                exc,
                agent_id=prepared.agent_id,
            )
            raise mapped from exc

    async def finalize_streamed_chat(
        self,
        *,
        prepared: PreparedChatRequest,
        content: str,
        status: ConversationMessageStatus,
        error_message: str | None = None,
    ) -> None:
        if prepared.assistant_message_id is None:
            return
        await self.conversation_service.finalize_assistant_message(
            assistant_message_id=prepared.assistant_message_id,
            content=content,
            status=status,
            error_message=error_message,
        )

    async def _finalize_prepared_completed(
        self,
        *,
        prepared: PreparedChatRequest,
        answer: str,
    ) -> None:
        if prepared.assistant_message_id is None:
            return
        await self.conversation_service.finalize_assistant_message(
            assistant_message_id=prepared.assistant_message_id,
            content=answer,
            status=ConversationMessageStatus.COMPLETED,
        )

    async def _finalize_prepared_error(
        self,
        *,
        prepared: PreparedChatRequest,
        error_message: str,
    ) -> None:
        if prepared.assistant_message_id is None:
            return
        await self.conversation_service.finalize_assistant_message(
            assistant_message_id=prepared.assistant_message_id,
            content="",
            status=ConversationMessageStatus.ERROR,
            error_message=error_message,
        )

    async def _ensure_agent_ready(
        self,
        *,
        user_id: int,
        agent_id: str,
    ) -> None:
        try:
            readiness = await self.openclaw_client.ensure_agent_runtime_ready(
                agent_id=agent_id,
            )
        except OpenClawError as exc:
            logger.warning(
                "OpenClaw readiness check failed before chat, user_id=%s, "
                "agent_id=%s, error_type=%s",
                user_id,
                agent_id,
                type(exc).__name__,
            )
            raise self._map_openclaw_error(exc, agent_id=agent_id) from exc

        if readiness.ready:
            await self._update_agent_status(
                user_id=user_id,
                provision_status=ProvisionStatus.READY,
                provision_error=None,
            )
            return

        reason = readiness.reason or readiness.error or "runtime_owner_not_ready"
        next_status = self._readiness_status(reason)
        await self._update_agent_status(
            user_id=user_id,
            provision_status=next_status,
            provision_error=reason,
        )
        if not readiness.ok and readiness.error == "agent_not_found":
            raise AppError(
                code="openclaw_agent_unavailable",
                message="Agent 当前不可用或上游资源不存在",
                status_code=status.HTTP_502_BAD_GATEWAY,
                details={
                    "agent_id": agent_id,
                    "provision_status": next_status.value,
                    "error": readiness.error,
                },
            )

        raise AppError(
            code="agent_not_ready",
            message="Agent is registered but OpenClaw runtime is still warming up",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={
                "agent_id": agent_id,
                "provision_status": next_status.value,
                "retry_after_ms": readiness.retry_after_ms,
                "reason": reason,
                "refreshed": readiness.refreshed,
            },
        )

    @staticmethod
    def _readiness_status(value: str) -> ProvisionStatus:
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

    @staticmethod
    def _chat_session_key(
        *,
        conversation_id: str | None,
        request_id: str | None,
    ) -> str:
        if conversation_id is not None:
            return f"webchat:{conversation_id}"
        if request_id is not None:
            return f"webchat:{request_id}"
        return f"webchat:{uuid4()}"

    async def _mark_runtime_not_ready(self, *, user_id: int) -> None:
        await self._update_agent_status(
            user_id=user_id,
            provision_status=ProvisionStatus.WARMING,
            provision_error="runtime_owner_not_ready",
        )

    async def _update_agent_status(
        self,
        *,
        user_id: int,
        provision_status: ProvisionStatus,
        provision_error: str | None,
    ) -> None:
        user_agent = await self.repository.get_by_user_id_for_update(user_id)
        if user_agent is None:
            raise ResourceNotFoundError(
                code="user_agent_not_found",
                message="当前用户 Agent 绑定不存在",
            )
        user_agent.provision_status = provision_status.value
        user_agent.provision_error = provision_error
        try:
            await self.db.commit()
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

    @staticmethod
    def _map_openclaw_error(
        exc: OpenClawError,
        *,
        agent_id: str,
    ) -> AppError:
        logger.warning(
            "OpenClaw chat failed, agent_id=%s, error_type=%s",
            agent_id,
            type(exc).__name__,
        )
        if isinstance(exc, OpenClawTimeoutError):
            return AppError(
                code="openclaw_timeout",
                message="后端等待 OpenClaw 响应超时，请稍后重试",
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        if isinstance(exc, OpenClawConnectionError):
            return AppError(
                code="openclaw_unavailable",
                message="OpenClaw 服务不可用",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if isinstance(
            exc,
            (OpenClawAuthenticationError, OpenClawConfigurationError),
        ):
            return AppError(
                code="openclaw_authentication_failed",
                message="OpenClaw 服务鉴权失败",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        if isinstance(exc, OpenClawRequestError):
            return AppError(
                code="openclaw_request_rejected",
                message="上游请求错误",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        if isinstance(exc, OpenClawConflictError):
            return AppError(
                code="openclaw_conflict",
                message="Agent 当前不可用或上游状态冲突",
                status_code=status.HTTP_409_CONFLICT,
            )
        if isinstance(exc, OpenClawResponseError):
            message = str(exc)
            if "rate limited" in message:
                return AppError(
                    code="openclaw_rate_limited",
                    message="OpenClaw 服务繁忙，请稍后重试",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            if "not found" in message:
                return AppError(
                    code="openclaw_agent_unavailable",
                    message="Agent 当前不可用或上游资源不存在",
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )
            if "HTTP 5" in message:
                return AppError(
                    code="openclaw_service_error",
                    message="OpenClaw 服务异常",
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )
            return AppError(
                code="openclaw_response_invalid",
                message="OpenClaw 服务响应异常",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return AppError(
            code="openclaw_chat_failed",
            message="OpenClaw 服务异常",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
