from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn
from uuid import uuid4

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversations import (
    AUTO_TITLE_LENGTH,
    DEFAULT_CONVERSATION_TITLE,
    MAX_CONVERSATION_TITLE_LENGTH,
    TERMINAL_MESSAGE_STATUSES,
    ConversationMessageRole,
    ConversationMessageStatus,
    ConversationStatus,
)
from app.core.errors import (
    AppError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage
from app.models.message_attachment import MessageAttachment
from app.repository.conversation_repository import ConversationRepository
from app.repository.attachment_repository import AttachmentRepository

SYSTEM_ACTOR = "system"


@dataclass(frozen=True, slots=True)
class ChatMessagePair:
    conversation: Conversation
    user_message: ConversationMessage
    assistant_message: ConversationMessage


class ConversationService:
    """Conversation business rules and transaction boundaries."""

    def __init__(
        self,
        db: AsyncSession,
        repository: ConversationRepository | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or ConversationRepository(db)

    async def create_for_user(
        self,
        *,
        user_id: int,
        title: str | None = None,
    ) -> Conversation:
        normalized_title = self._normalize_create_title(title)
        conversation = Conversation(
            id=str(uuid4()),
            user_id=user_id,
            title=normalized_title,
            status=ConversationStatus.ACTIVE.value,
            is_deleted=False,
            created_by=SYSTEM_ACTOR,
            updated_by=SYSTEM_ACTOR,
        )
        try:
            await self.repository.create(conversation)
            await self._commit()
            await self.db.refresh(conversation)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return conversation

    async def list_for_user(
        self,
        *,
        user_id: int,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[Conversation], str | None]:
        offset = self._parse_cursor(cursor)
        items = await self.repository.list_for_user(
            user_id=user_id,
            offset=offset,
            limit=limit,
        )
        total = await self.repository.count_for_user(user_id=user_id)
        next_offset = offset + len(items)
        next_cursor = str(next_offset) if next_offset < total else None
        return items, next_cursor

    async def get_for_user(
        self,
        *,
        conversation_id: str,
        user_id: int,
    ) -> Conversation:
        conversation = await self.repository.get_for_user(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if conversation is None:
            raise self._not_found()
        return conversation

    async def list_messages_for_user(
        self,
        *,
        conversation_id: str,
        user_id: int,
    ) -> list[ConversationMessage]:
        await self.get_for_user(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return await self.repository.list_messages(
            conversation_id=conversation_id,
        )

    async def list_message_attachment_links(
        self,
        *,
        message_ids: list[int],
    ):
        return await AttachmentRepository(self.db).list_for_message_ids(
            message_ids=message_ids,
        )

    async def update_title(
        self,
        *,
        conversation_id: str,
        user_id: int,
        title: str,
    ) -> Conversation:
        conversation = await self.get_for_user(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        conversation.title = self._normalize_required_title(title)
        conversation.updated_by = SYSTEM_ACTOR
        try:
            await self._commit()
            await self.db.refresh(conversation)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return conversation

    async def soft_delete(
        self,
        *,
        conversation_id: str,
        user_id: int,
    ) -> None:
        conversation = await self.get_for_user(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if await self.repository.has_active_message(
            conversation_id=conversation.id,
        ):
            raise ResourceConflictError(
                code="conversation_active_stream",
                message="当前会话正在生成中，请先停止生成",
            )
        conversation.is_deleted = True
        conversation.updated_by = SYSTEM_ACTOR
        try:
            await self._commit()
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise

    async def create_chat_message_pair(
        self,
        *,
        user_id: int,
        conversation_id: str,
        user_content: str,
        request_id: str | None,
        assistant_status: ConversationMessageStatus,
        attachment_ids: list[str] | None = None,
    ) -> ChatMessagePair:
        now = self._now()
        try:
            conversation = await self.repository.get_for_user_for_update(
                conversation_id=conversation_id,
                user_id=user_id,
            )
            if conversation is None:
                raise self._not_found()

            if await self.repository.has_active_message(
                conversation_id=conversation.id,
            ):
                raise ResourceConflictError(
                    code="conversation_generation_running",
                    message="当前会话已有生成请求进行中",
                )

            max_sequence_no = await self.repository.max_sequence_no(
                conversation_id=conversation.id,
            )
            first_sequence_no = 1 if max_sequence_no is None else max_sequence_no + 1
            if (
                max_sequence_no is None
                and conversation.title == DEFAULT_CONVERSATION_TITLE
            ):
                conversation.title = self._auto_title(user_content)

            user_message = ConversationMessage(
                conversation_id=conversation.id,
                role=ConversationMessageRole.USER.value,
                content=user_content,
                status=ConversationMessageStatus.COMPLETED.value,
                request_id=None,
                sequence_no=first_sequence_no,
                created_by=SYSTEM_ACTOR,
                updated_by=SYSTEM_ACTOR,
            )
            assistant_message = ConversationMessage(
                conversation_id=conversation.id,
                role=ConversationMessageRole.ASSISTANT.value,
                content="",
                status=assistant_status.value,
                request_id=request_id,
                sequence_no=first_sequence_no + 1,
                created_by=SYSTEM_ACTOR,
                updated_by=SYSTEM_ACTOR,
            )
            conversation.last_message_at = now
            conversation.updated_by = SYSTEM_ACTOR
            await self.repository.add_message(user_message)
            await self.repository.add_message(assistant_message)
            if attachment_ids:
                self.db.add_all(
                    [
                        MessageAttachment(
                            message_id=user_message.id,
                            attachment_id=attachment_id,
                            sort_order=index,
                        )
                        for index, attachment_id in enumerate(attachment_ids)
                    ]
                )
                await self.db.flush()
            await self._commit()
            await self.db.refresh(conversation)
            await self.db.refresh(user_message)
            await self.db.refresh(assistant_message)
        except IntegrityError as exc:
            await self._raise_message_conflict(exc)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return ChatMessagePair(
            conversation=conversation,
            user_message=user_message,
            assistant_message=assistant_message,
        )

    async def finalize_assistant_message(
        self,
        *,
        assistant_message_id: int,
        content: str,
        status: ConversationMessageStatus,
        error_message: str | None = None,
    ) -> ConversationMessage:
        if status.value not in TERMINAL_MESSAGE_STATUSES:
            raise ValueError("assistant message final status must be terminal")
        try:
            message = await self.repository.get_message_for_update(
                message_id=assistant_message_id,
            )
            if message is None:
                raise ResourceNotFoundError(
                    code="conversation_message_not_found",
                    message="会话消息不存在",
                )
            if message.status in TERMINAL_MESSAGE_STATUSES:
                return message

            message.content = content
            message.status = status.value
            message.error_message = self._safe_error_summary(error_message)
            message.updated_by = SYSTEM_ACTOR
            message.conversation.last_message_at = self._now()
            message.conversation.updated_by = SYSTEM_ACTOR
            await self._commit()
            await self.db.refresh(message)
        except Exception:
            if self.db.in_transaction():
                await self.db.rollback()
            raise
        return message

    async def _commit(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self._raise_message_conflict(exc)
        except Exception:
            await self.db.rollback()
            raise

    @staticmethod
    def _not_found() -> ResourceNotFoundError:
        return ResourceNotFoundError(
            code="conversation_not_found",
            message="会话不存在",
        )

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        normalized = cursor.strip()
        if not normalized.isdecimal():
            raise AppError(
                code="invalid_conversation_cursor",
                message="会话列表游标无效",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return int(normalized)

    @staticmethod
    def _normalize_create_title(title: str | None) -> str:
        if title is None:
            return DEFAULT_CONVERSATION_TITLE
        return ConversationService._normalize_required_title(title)

    @staticmethod
    def _normalize_required_title(title: str) -> str:
        normalized = title.strip()
        if not normalized:
            raise AppError(
                code="conversation_title_empty",
                message="会话标题不能为空",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        if len(normalized) > MAX_CONVERSATION_TITLE_LENGTH:
            raise AppError(
                code="conversation_title_too_long",
                message="会话标题不能超过100个字符",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        return normalized

    @staticmethod
    def _auto_title(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return DEFAULT_CONVERSATION_TITLE
        return normalized[:AUTO_TITLE_LENGTH]

    @staticmethod
    def _safe_error_summary(error_message: str | None) -> str | None:
        if error_message is None:
            return None
        return " ".join(error_message.split())[:1000]

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    async def _raise_message_conflict(
        self,
        exc: IntegrityError,
    ) -> NoReturn:
        await self.db.rollback()
        raise ResourceConflictError(
            code="conversation_message_conflict",
            message="会话消息写入冲突，请重试",
        ) from exc
