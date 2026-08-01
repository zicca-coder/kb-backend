import json
from typing import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.dependencies import get_openclaw_client
from app.core.errors import OpenClawConnectionError
from app.models.conversation_message import ConversationMessage
from app.models.user_agent import UserAgent
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
    OpenClawChatResult,
)

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
PASSWORD = "Kb@123456"


class RecordingOpenClawClient:
    def __init__(
        self,
        *,
        answer: str = "同步回答",
        stream_deltas: list[str] | None = None,
        stream_exc: Exception | None = None,
    ) -> None:
        self.answer = answer
        self.stream_deltas = stream_deltas or ["流式", "回答"]
        self.stream_exc = stream_exc
        self.chat_calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str, str]] = []
        self.chat_session_keys: list[str | None] = []
        self.stream_session_keys: list[str | None] = []

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        return AgentProvisionResult(agent_id=f"web-user-{external_user_id}")

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        return AgentRuntimeEnsureReadyResult(
            ok=True,
            agentId=agent_id,
            ready=True,
            refreshed=True,
            retryAfterMs=0,
        )

    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
    ) -> OpenClawChatResult:
        self.chat_calls.append((agent_id, openclaw_user, message))
        self.chat_session_keys.append(session_key)
        return OpenClawChatResult(answer=self.answer)

    async def stream_chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        session_key: str | None = None,
    ) -> AsyncIterator[str]:
        self.stream_calls.append((agent_id, openclaw_user, message))
        self.stream_session_keys.append(session_key)
        for delta in self.stream_deltas:
            yield delta
        if self.stream_exc is not None:
            raise self.stream_exc


def _install_openclaw_client(
    client: TestClient,
    openclaw_client: RecordingOpenClawClient,
) -> None:
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: openclaw_client
    )


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(
    client: TestClient,
    *,
    username: str,
    phone: str,
) -> dict[str, object]:
    response = client.post(
        REGISTER_URL,
        json={
            "username": username,
            "password": PASSWORD,
            "display_name": username,
            "phone": phone,
            "email": f"{username}@example.com",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def _login(client: TestClient, *, username: str) -> str:
    response = client.post(
        LOGIN_URL,
        json={"account": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def _stored_agent(db_session: Session, user_id: str) -> UserAgent:
    return db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user_id))
    ).scalar_one()


def _set_agent(
    db_session: Session,
    user_id: str,
    *,
    agent_id: str,
    provision_status: str = "ready",
) -> None:
    user_agent = _stored_agent(db_session, user_id)
    user_agent.agent_id = agent_id
    user_agent.provision_status = provision_status
    db_session.commit()


def _create_ready_user(
    client: TestClient,
    db_session: Session,
    *,
    username: str,
    phone: str,
) -> tuple[dict[str, object], str]:
    user = _register(client, username=username, phone=phone)
    _set_agent(db_session, str(user["id"]), agent_id=f"agent-{username}")
    return user, _login(client, username=username)


def _create_conversation(
    client: TestClient,
    *,
    token: str,
    title: str | None = None,
) -> str:
    response = client.post(
        "/api/conversations",
        headers=_authorization(token),
        json={} if title is None else {"title": title},
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def _parse_sse_events(text_value: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in text_value.strip().split("\n\n"):
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            if line.startswith("data: "):
                data = line.removeprefix("data: ")
        events.append((event_name, json.loads(data)))
    return events


def _messages(db_session: Session, conversation_id: str) -> list[ConversationMessage]:
    return list(
        db_session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_no)
        )
        .scalars()
        .all()
    )


def test_create_conversation_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/conversations", json={})

    assert response.status_code == 401


def test_current_user_can_create_list_update_delete_conversation(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_crud",
        phone="13900139001",
    )

    conversation_id = _create_conversation(client, token=token, title=" 初始标题 ")
    detail = client.get(
        f"/api/conversations/{conversation_id}",
        headers=_authorization(token),
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["title"] == "初始标题"

    update = client.patch(
        f"/api/conversations/{conversation_id}",
        headers=_authorization(token),
        json={"title": " 新标题 "},
    )
    assert update.status_code == 200
    assert update.json()["data"]["title"] == "新标题"

    listed = client.get("/api/conversations", headers=_authorization(token))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]["items"]] == [
        conversation_id
    ]

    deleted = client.delete(
        f"/api/conversations/{conversation_id}",
        headers=_authorization(token),
    )
    assert deleted.status_code == 200
    listed_after_delete = client.get(
        "/api/conversations",
        headers=_authorization(token),
    )
    assert listed_after_delete.json()["data"]["items"] == []


def test_current_user_only_sees_own_conversations(
    client: TestClient,
    db_session: Session,
) -> None:
    _user_a, token_a = _create_ready_user(
        client,
        db_session,
        username="conv_owner_a",
        phone="13900139002",
    )
    _user_b, token_b = _create_ready_user(
        client,
        db_session,
        username="conv_owner_b",
        phone="13900139003",
    )
    conversation_a = _create_conversation(client, token=token_a)
    conversation_b = _create_conversation(client, token=token_b)

    response_a = client.get("/api/conversations", headers=_authorization(token_a))
    response_b = client.get("/api/conversations", headers=_authorization(token_b))

    assert [item["id"] for item in response_a.json()["data"]["items"]] == [
        conversation_a
    ]
    assert [item["id"] for item in response_b.json()["data"]["items"]] == [
        conversation_b
    ]
    cross_update = client.patch(
        f"/api/conversations/{conversation_b}",
        headers=_authorization(token_a),
        json={"title": "越权"},
    )
    assert cross_update.status_code == 404


def test_conversation_list_orders_by_recent_message_time(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_sort",
        phone="13900139004",
    )
    older = _create_conversation(client, token=token, title="older")
    newer = _create_conversation(client, token=token, title="newer")
    db_session.execute(
        text(
            "UPDATE conversations SET last_message_at = :value WHERE id = :id"
        ),
        {"value": "2026-08-01 10:00:00", "id": older},
    )
    db_session.execute(
        text(
            "UPDATE conversations SET last_message_at = :value WHERE id = :id"
        ),
        {"value": "2026-08-01 11:00:00", "id": newer},
    )
    db_session.commit()

    response = client.get("/api/conversations", headers=_authorization(token))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["items"]] == [
        newer,
        older,
    ]


def test_chat_with_conversation_persists_completed_messages(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient(answer="完整回答")
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_chat_sync",
        phone="13900139005",
    )
    conversation_id = _create_conversation(client, token=token)

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": " 第一条问题\n换行 ", "conversation_id": conversation_id},
    )

    assert response.status_code == 200
    db_session.expire_all()
    messages = _messages(db_session, conversation_id)
    assert [(m.role, m.status, m.content, m.sequence_no) for m in messages] == [
        ("user", "completed", "第一条问题\n换行", 1),
        ("assistant", "completed", "完整回答", 2),
    ]
    detail = client.get(
        f"/api/conversations/{conversation_id}",
        headers=_authorization(token),
    )
    assert detail.json()["data"]["title"] == "第一条问题 换行"


def test_stream_chat_persists_completed_assistant_delta_content(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient(stream_deltas=["第一段", "第二段"])
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_chat_stream",
        phone="13900139006",
    )
    conversation_id = _create_conversation(client, token=token)

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={
            "message": "你好",
            "stream": True,
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event for event, _data in events] == [
        "start",
        "delta",
        "delta",
        "done",
    ]
    db_session.expire_all()
    messages = _messages(db_session, conversation_id)
    assert [(m.role, m.status, m.content, m.sequence_no) for m in messages] == [
        ("user", "completed", "你好", 1),
        ("assistant", "completed", "第一段第二段", 2),
    ]
    history = client.get(
        f"/api/conversations/{conversation_id}/messages",
        headers=_authorization(token),
    )
    assert history.status_code == 200
    assert "error_message" not in history.text


def test_stream_chat_persists_error_with_partial_content(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient(
        stream_deltas=["部分内容"],
        stream_exc=OpenClawConnectionError("internal path /secret"),
    )
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_chat_error",
        phone="13900139007",
    )
    conversation_id = _create_conversation(client, token=token)

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={
            "message": "你好",
            "stream": True,
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    assert "internal path" not in response.text
    db_session.expire_all()
    messages = _messages(db_session, conversation_id)
    assert messages[1].status == "error"
    assert messages[1].content == "部分内容"
    assert messages[1].error_message == "openclaw_unavailable: OpenClaw 服务不可用"


def test_deleted_or_foreign_conversation_cannot_be_used_for_chat_or_history(
    client: TestClient,
    db_session: Session,
) -> None:
    _user_a, token_a = _create_ready_user(
        client,
        db_session,
        username="conv_secure_a",
        phone="13900139008",
    )
    _user_b, token_b = _create_ready_user(
        client,
        db_session,
        username="conv_secure_b",
        phone="13900139009",
    )
    foreign_conversation = _create_conversation(client, token=token_b)
    own_conversation = _create_conversation(client, token=token_a)
    client.delete(
        f"/api/conversations/{own_conversation}",
        headers=_authorization(token_a),
    )

    foreign_history = client.get(
        f"/api/conversations/{foreign_conversation}/messages",
        headers=_authorization(token_a),
    )
    deleted_chat = client.post(
        "/api/chat",
        headers=_authorization(token_a),
        json={"message": "你好", "conversation_id": own_conversation},
    )

    assert foreign_history.status_code == 404
    assert deleted_chat.status_code == 404


def test_conversation_rejects_existing_active_generation(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_active",
        phone="13900139010",
    )
    conversation_id = _create_conversation(client, token=token)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation_id,
            role="assistant",
            content="",
            status="streaming",
            request_id="11111111-1111-1111-1111-111111111111",
            sequence_no=1,
            created_by="system",
            updated_by="system",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/chat",
        headers=_authorization(token),
        json={"message": "你好", "conversation_id": conversation_id},
    )

    assert response.status_code == 409
    assert openclaw_client.chat_calls == []


def test_invalid_conversation_id_gets_validation_error(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, token = _create_ready_user(
        client,
        db_session,
        username="conv_invalid",
        phone="13900139011",
    )

    response = client.get(
        "/api/conversations/not-a-uuid/messages",
        headers=_authorization(token),
    )

    assert response.status_code == 422
