from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

ChatMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=10000),
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

    message: ChatMessage = ""
    attachment_ids: list[str] = Field(default_factory=list)
    stream: StrictBool = False
    conversation_id: ConversationId | None = None

    @model_validator(mode="after")
    def keep_legacy_empty_message_validation(self) -> Self:
        if (
            "message" in self.model_fields_set
            and "attachment_ids" not in self.model_fields_set
            and not self.message
        ):
            raise ValueError("message must be a non-empty string")
        return self


class ChatResponse(BaseModel):
    answer: str


class ChatCancelResponse(BaseModel):
    request_id: str
    status: str
