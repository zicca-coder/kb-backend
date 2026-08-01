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
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
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
