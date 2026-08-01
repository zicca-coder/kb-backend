from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversations import ACTIVE_MESSAGE_STATUSES
from app.models.conversation import Conversation
from app.models.conversation_message import ConversationMessage


class ConversationRepository:
    """Conversation and message persistence helpers."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, conversation: Conversation) -> Conversation:
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def get_for_user(
        self,
        *,
        conversation_id: str,
        user_id: int,
    ) -> Conversation | None:
        statement = self._for_user_statement(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_for_user_for_update(
        self,
        *,
        conversation_id: str,
        user_id: int,
    ) -> Conversation | None:
        statement = self._for_user_statement(
            conversation_id=conversation_id,
            user_id=user_id,
        ).with_for_update()
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: int,
        offset: int,
        limit: int,
    ) -> list[Conversation]:
        statement = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.is_deleted.is_(False),
            )
            .order_by(
                Conversation.last_message_at.desc(),
                Conversation.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def count_for_user(self, *, user_id: int) -> int:
        statement = select(func.count(Conversation.id)).where(
            Conversation.user_id == user_id,
            Conversation.is_deleted.is_(False),
        )
        result = await self.db.execute(statement)
        return result.scalar_one()

    async def list_messages(
        self,
        *,
        conversation_id: str,
    ) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_no.asc())
        )
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def max_sequence_no(
        self,
        *,
        conversation_id: str,
    ) -> int | None:
        statement = select(func.max(ConversationMessage.sequence_no)).where(
            ConversationMessage.conversation_id == conversation_id
        )
        result = await self.db.execute(statement)
        return result.scalar_one()

    async def has_active_message(
        self,
        *,
        conversation_id: str,
    ) -> bool:
        statement = (
            select(ConversationMessage.id)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.status.in_(ACTIVE_MESSAGE_STATUSES),
            )
            .limit(1)
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none() is not None

    async def get_message_for_update(
        self,
        *,
        message_id: int,
    ) -> ConversationMessage | None:
        statement = (
            select(ConversationMessage)
            .where(ConversationMessage.id == message_id)
            .with_for_update()
        )
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def add_message(
        self,
        message: ConversationMessage,
    ) -> ConversationMessage:
        self.db.add(message)
        await self.db.flush()
        return message

    @staticmethod
    def _for_user_statement(
        *,
        conversation_id: str,
        user_id: int,
    ) -> Select[tuple[Conversation]]:
        return select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.is_deleted.is_(False),
        )
