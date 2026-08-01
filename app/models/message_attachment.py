from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import BigIntIdMixin

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.conversation_message import ConversationMessage


class MessageAttachment(BigIntIdMixin, Base):
    """Ordered attachment reference for a persisted chat message."""

    __tablename__ = "message_attachments"

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "attachment_id",
            name="uk_message_attachments_message_attachment",
        ),
        UniqueConstraint(
            "message_id",
            "sort_order",
            name="uk_message_attachments_message_sort",
        ),
        Index(
            "ix_message_attachments_attachment",
            "attachment_id",
        ),
        {
            "comment": "聊天消息附件关联表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    message_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey(
            "conversation_messages.id",
            name="fk_message_attachments_message",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="Conversation message ID",
    )

    attachment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "attachments.id",
            name="fk_message_attachments_attachment",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="Attachment UUID",
    )

    sort_order: Mapped[int] = mapped_column(
        nullable=False,
        comment="Attachment order within message",
    )

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        comment="创建时间",
    )

    message: Mapped["ConversationMessage"] = relationship(
        back_populates="attachment_links",
        lazy="selectin",
    )
    attachment: Mapped["Attachment"] = relationship(
        back_populates="message_links",
        lazy="selectin",
    )
