from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

ChatMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: ChatMessage


class ChatResponse(BaseModel):
    answer: str
