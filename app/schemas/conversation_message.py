from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.core.conversations import (
    ConversationMessageRole,
    ConversationMessageStatus,
)
from app.schemas.attachment import AttachmentRead

MessageId = Annotated[str, BeforeValidator(lambda value: str(value))]


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: MessageId
    conversation_id: str
    role: ConversationMessageRole
    content: str
    status: ConversationMessageStatus
    request_id: str | None
    sequence_no: int
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentRead] = Field(default_factory=list)

    @classmethod
    def from_message(
        cls,
        message,
        *,
        attachments: list[AttachmentRead] | None = None,
    ) -> "ConversationMessageRead":
        return cls.model_validate(
            {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "role": message.role,
                "content": message.content,
                "status": message.status,
                "request_id": message.request_id,
                "sequence_no": message.sequence_no,
                "created_at": message.created_at,
                "updated_at": message.updated_at,
                "attachments": attachments or [],
            }
        )


class ConversationMessageList(BaseModel):
    items: list[ConversationMessageRead]
