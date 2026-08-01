import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from app.core.errors import ResourceConflictError, ResourceNotFoundError


class ChatStreamStatus(StrEnum):
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES = {
    ChatStreamStatus.CANCELLED,
    ChatStreamStatus.COMPLETED,
    ChatStreamStatus.FAILED,
}


@dataclass(slots=True)
class ChatStreamRecord:
    request_id: str
    user_id: int
    conversation_id: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    status: ChatStreamStatus = ChatStreamStatus.RUNNING
    updated_at: float = field(default_factory=time.monotonic)


class ChatStreamManager:
    def __init__(
        self,
        *,
        terminal_ttl_seconds: float = 300,
        max_terminal_records: int = 1000,
    ) -> None:
        self._records: dict[str, ChatStreamRecord] = {}
        self._terminal_records: dict[str, ChatStreamRecord] = {}
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._max_terminal_records = max_terminal_records
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        user_id: int,
        conversation_id: str | None = None,
    ) -> ChatStreamRecord:
        async with self._lock:
            self._purge_terminal_locked()
            if conversation_id is not None:
                if self._has_running_conversation_locked(
                    user_id=user_id,
                    conversation_id=conversation_id,
                ):
                    raise ResourceConflictError(
                        code="chat_stream_conflict",
                        message="当前会话已有生成请求进行中",
                    )
            request_id = str(uuid4())
            record = ChatStreamRecord(
                request_id=request_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            self._records[request_id] = record

        return record

    async def set_task(
        self,
        *,
        request_id: str,
        task: asyncio.Task[None],
    ) -> None:
        async with self._lock:
            record = self._records.get(request_id)
            if record is not None:
                record.task = task
                record.updated_at = time.monotonic()

    async def cancel(
        self,
        *,
        request_id: str,
        user_id: int,
    ) -> ChatStreamStatus:
        async with self._lock:
            record = self._records.get(request_id)
            if record is None:
                terminal_record = self._terminal_records.get(request_id)
                if (
                    terminal_record is not None
                    and terminal_record.user_id == user_id
                ):
                    return terminal_record.status
                raise ResourceNotFoundError(
                    code="chat_stream_not_found",
                    message="生成请求不存在",
                )

            if record.user_id != user_id:
                raise ResourceNotFoundError(
                    code="chat_stream_not_found",
                    message="生成请求不存在",
                )

            if record.status in TERMINAL_STATUSES:
                return record.status
            if record.status == ChatStreamStatus.RUNNING:
                record.status = ChatStreamStatus.CANCELLING
            record.cancel_event.set()
            if record.task is not None and not record.task.done():
                record.task.cancel()
            record.updated_at = time.monotonic()
            return record.status

    async def finish(
        self,
        *,
        request_id: str,
        status: ChatStreamStatus,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError("finish status must be terminal")
        async with self._lock:
            record = self._records.pop(request_id, None)
            if record is None:
                record = self._terminal_records.get(request_id)
                if record is None:
                    return
            record.status = status
            record.task = None
            record.updated_at = time.monotonic()
            self._terminal_records[request_id] = record
            self._purge_terminal_locked()

    async def get_status_for_user(
        self,
        *,
        request_id: str,
        user_id: int,
    ) -> ChatStreamStatus:
        async with self._lock:
            record = (
                self._records.get(request_id)
                or self._terminal_records.get(request_id)
            )
            if record is None or record.user_id != user_id:
                raise ResourceNotFoundError(
                    code="chat_stream_not_found",
                    message="生成请求不存在",
                )
            return record.status

    async def active_count(self) -> int:
        async with self._lock:
            return len(self._records)

    def _purge_terminal_locked(self) -> None:
        now = time.monotonic()
        expired_ids = [
            request_id
            for request_id, record in self._terminal_records.items()
            if now - record.updated_at > self._terminal_ttl_seconds
        ]
        for request_id in expired_ids:
            self._terminal_records.pop(request_id, None)

        overflow = len(self._terminal_records) - self._max_terminal_records
        if overflow <= 0:
            return
        oldest_ids = sorted(
            self._terminal_records,
            key=lambda key: self._terminal_records[key].updated_at,
        )[:overflow]
        for request_id in oldest_ids:
            self._terminal_records.pop(request_id, None)

    def _has_running_conversation_locked(
        self,
        *,
        user_id: int,
        conversation_id: str,
    ) -> bool:
        for record in self._records.values():
            if (
                record.user_id != user_id
                or record.conversation_id != conversation_id
                or record.status in TERMINAL_STATUSES
            ):
                continue
            return True
        return False


chat_stream_manager = ChatStreamManager()
