from enum import StrEnum


DEFAULT_CONVERSATION_TITLE = "新对话"
MAX_CONVERSATION_TITLE_LENGTH = 100
AUTO_TITLE_LENGTH = 30


class ConversationStatus(StrEnum):
    ACTIVE = "active"


class ConversationMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationMessageStatus(StrEnum):
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


ACTIVE_MESSAGE_STATUSES = {
    ConversationMessageStatus.PENDING.value,
    ConversationMessageStatus.STREAMING.value,
}

TERMINAL_MESSAGE_STATUSES = {
    ConversationMessageStatus.COMPLETED.value,
    ConversationMessageStatus.CANCELLED.value,
    ConversationMessageStatus.ERROR.value,
}
