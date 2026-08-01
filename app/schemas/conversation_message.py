from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.core.conversations import (
    ConversationMessageRole,
    ConversationMessageStatus,
)

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


class ConversationMessageList(BaseModel):
    items: list[ConversationMessageRead]
