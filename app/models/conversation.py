from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.conversations import (
    ConversationStatus,
    DEFAULT_CONVERSATION_TITLE,
)
from app.models.base import Base
from app.models.mixins import AuditMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.conversation_message import ConversationMessage
    from app.models.user import User


class Conversation(AuditMixin, SoftDeleteMixin, Base):
    """User-owned chat conversation."""

    __tablename__ = "conversations"

    __table_args__ = (
        Index(
            "ix_conversations_user_deleted_last_message",
            "user_id",
            "is_deleted",
            "last_message_at",
        ),
        {
            "comment": "用户聊天会话表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="Conversation UUID",
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_conversations_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="Owner user ID",
    )

    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=DEFAULT_CONVERSATION_TITLE,
        server_default=DEFAULT_CONVERSATION_TITLE,
        comment="Conversation title",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConversationStatus.ACTIVE.value,
        server_default=ConversationStatus.ACTIVE.value,
        comment="Conversation status",
    )

    last_message_at: Mapped[datetime | None] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=True,
        comment="Last message time for ordering",
    )

    user: Mapped["User"] = relationship(lazy="selectin")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ConversationMessage.sequence_no",
    )
