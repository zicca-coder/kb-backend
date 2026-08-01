from typing import Annotated

from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints

ChatMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: ChatMessage
    stream: StrictBool = False


class ChatResponse(BaseModel):
    answer: str


class ChatCancelResponse(BaseModel):
    request_id: str
    status: str
