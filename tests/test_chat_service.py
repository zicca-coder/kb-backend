import asyncio
from collections.abc import Awaitable
from typing import TypeVar

import pytest

from app.core.errors import ResourceConflictError
from app.models.user_agent import UserAgent
from app.schemas.openclaw import OpenClawChatResult
from app.services.chat_service import ChatService

T = TypeVar("T")


def run_async(awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


class FakeRepository:
    def __init__(self, user_agent: UserAgent | None) -> None:
        self.user_agent = user_agent

    async def get_by_user_id(self, user_id: int) -> UserAgent | None:
        return self.user_agent


class RecordingChatClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
    ) -> OpenClawChatResult:
        self.calls.append((agent_id, openclaw_user, message))
        return OpenClawChatResult(answer="回答")


def make_user_agent(*, provision_status: str) -> UserAgent:
    return UserAgent(
        id=1,
        user_id=123,
        agent_id=None,
        provision_status=provision_status,
        is_deleted=False,
    )


@pytest.mark.parametrize(
    "provision_status",
    ["pending", "provisioning", "failed"],
)
def test_chat_service_rejects_not_ready_agents_without_openclaw_call(
    provision_status: str,
) -> None:
    chat_client = RecordingChatClient()
    service = ChatService(
        None,  # type: ignore[arg-type]
        chat_client,
        repository=FakeRepository(
            make_user_agent(provision_status=provision_status)
        ),  # type: ignore[arg-type]
    )

    async def scenario() -> None:
        with pytest.raises(ResourceConflictError):
            await service.chat_for_user(user_id=123, message="你好")

    run_async(scenario())

    assert chat_client.calls == []
