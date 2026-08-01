from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.conversations import (
    ConversationMessageRole,
    ConversationMessageStatus,
)
from app.models.base import Base
from app.models.mixins import AuditMixin, BigIntIdMixin


class ConversationMessage(BigIntIdMixin, AuditMixin, Base):
    """Persisted chat message within a conversation."""

    __tablename__ = "conversation_messages"

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_no",
            name="uk_conversation_messages_conversation_sequence",
        ),
        Index(
            "ix_conversation_messages_conversation_sequence",
            "conversation_id",
            "sequence_no",
        ),
        Index(
            "ix_conversation_messages_request_id",
            "request_id",
        ),
        {
            "comment": "用户聊天消息表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "conversations.id",
            name="fk_conversation_messages_conversation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="Conversation UUID",
    )

    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Message role",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Message content",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConversationMessageStatus.PENDING.value,
        server_default=ConversationMessageStatus.PENDING.value,
        comment="Message status",
    )

    request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="Streaming request UUID",
    )

    sequence_no: Mapped[int] = mapped_column(
        nullable=False,
        comment="Message sequence number within conversation",
    )

    error_message: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Internal safe error summary",
    )

    conversation = relationship(
        "Conversation",
        back_populates="messages",
        lazy="selectin",
    )
