from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.attachments import (
    AttachmentPurpose,
    AttachmentStatus,
)
from app.models.base import Base
from app.models.mixins import AuditMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.message_attachment import MessageAttachment
    from app.models.user import User


class Attachment(AuditMixin, SoftDeleteMixin, Base):
    """User-owned object-storage attachment metadata."""

    __tablename__ = "attachments"

    __table_args__ = (
        Index(
            "ix_attachments_user_status_deleted",
            "user_id",
            "status",
            "is_deleted",
        ),
        Index("ix_attachments_conversation", "conversation_id"),
        Index("ix_attachments_sha256", "sha256"),
        {
            "comment": "聊天附件元数据表",
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="Attachment UUID",
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_attachments_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
        comment="Owner user ID",
    )

    conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "conversations.id",
            name="fk_attachments_conversation",
            ondelete="SET NULL",
            onupdate="RESTRICT",
        ),
        nullable=True,
        comment="Optional conversation UUID",
    )

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Original safe filename",
    )

    bucket_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Private object storage bucket",
    )

    object_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
        comment="Object storage key",
    )

    content_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Response content type",
    )

    detected_mime_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Server detected MIME type",
    )

    extension: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Lowercase file extension",
    )

    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="File size in bytes",
    )

    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 digest",
    )

    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Attachment category",
    )

    purpose: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=AttachmentPurpose.CHAT_ATTACHMENT.value,
        server_default=AttachmentPurpose.CHAT_ATTACHMENT.value,
        comment="Attachment purpose",
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AttachmentStatus.UPLOADING.value,
        server_default=AttachmentStatus.UPLOADING.value,
        comment="Attachment status",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Safe processing error",
    )

    user: Mapped["User"] = relationship(lazy="selectin")
    conversation: Mapped["Conversation | None"] = relationship(lazy="selectin")
    message_links: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="attachment",
        lazy="selectin",
    )
