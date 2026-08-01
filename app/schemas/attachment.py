from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.core.attachments import CHAT_ATTACHMENT_PREVIEW_URL

AttachmentId = Annotated[str, BeforeValidator(lambda value: str(value))]


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: AttachmentId
    filename: str
    content_type: str
    file_size: int
    category: str
    status: str
    preview_url: str

    @classmethod
    def from_attachment(cls, attachment) -> "AttachmentRead":
        return cls.model_validate(
            {
                "attachment_id": attachment.id,
                "filename": attachment.original_filename,
                "content_type": attachment.content_type,
                "file_size": attachment.file_size,
                "category": attachment.category,
                "status": attachment.status,
                "preview_url": CHAT_ATTACHMENT_PREVIEW_URL.format(
                    attachment_id=attachment.id,
                ),
            }
        )


class AttachmentDetail(AttachmentRead):
    conversation_id: str | None = None
    purpose: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_attachment(cls, attachment) -> "AttachmentDetail":
        return cls.model_validate(
            {
                "attachment_id": attachment.id,
                "filename": attachment.original_filename,
                "content_type": attachment.content_type,
                "file_size": attachment.file_size,
                "category": attachment.category,
                "status": attachment.status,
                "preview_url": CHAT_ATTACHMENT_PREVIEW_URL.format(
                    attachment_id=attachment.id,
                ),
                "conversation_id": attachment.conversation_id,
                "purpose": attachment.purpose,
                "created_at": attachment.created_at,
                "updated_at": attachment.updated_at,
            }
        )
