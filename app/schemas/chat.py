from typing import Annotated

from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints

ChatMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
]
ConversationId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=36,
        max_length=36,
        pattern=(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}$"
        ),
    ),
]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: ChatMessage
    stream: StrictBool = False
    conversation_id: ConversationId | None = None


class ChatResponse(BaseModel):
    answer: str


class ChatCancelResponse(BaseModel):
    request_id: str
    status: str
