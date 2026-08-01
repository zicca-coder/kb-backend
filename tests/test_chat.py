import asyncio
import json
from typing import AsyncIterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_openclaw_client
from app.core.errors import (
    OpenClawAuthenticationError,
    OpenClawConflictError,
    OpenClawConnectionError,
    OpenClawRequestError,
    OpenClawResponseError,
    OpenClawRuntimeNotReadyError,
    OpenClawTimeoutError,
)
from app.models.user_agent import UserAgent
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
    OpenClawChatResult,
)
from app.services.chat_stream_manager import (
    ChatStreamStatus,
    chat_stream_manager,
)

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
CHAT_URL = "/api/chat"
PASSWORD = "Kb@123456"
TEST_TOKEN = "secret-gateway-token"


class RecordingOpenClawClient:
    def __init__(
        self,
        exc: Exception | None = None,
        readiness: AgentRuntimeEnsureReadyResult | None = None,
        stream_deltas: list[str] | None = None,
        stream_exc: Exception | None = None,
    ) -> None:
        self.exc = exc
        self.readiness = readiness
        self.stream_deltas = stream_deltas or ["知识库", "回答"]
        self.stream_exc = stream_exc
        self.provision_calls: list[str] = []
        self.chat_calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str, str]] = []
        self.readiness_calls: list[str] = []

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        normalized = str(external_user_id)
        self.provision_calls.append(normalized)
        return AgentProvisionResult(agent_id=f"web-user-{normalized}")

    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
    ) -> OpenClawChatResult:
        self.chat_calls.append((agent_id, openclaw_user, message))
        if self.exc is not None:
            raise self.exc
        return OpenClawChatResult(answer="知识库回答")

    async def stream_chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
    ) -> AsyncIterator[str]:
        self.stream_calls.append((agent_id, openclaw_user, message))
        for delta in self.stream_deltas:
            yield delta
        if self.stream_exc is not None:
            raise self.stream_exc

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        self.readiness_calls.append(agent_id)
        return self.readiness or AgentRuntimeEnsureReadyResult(
            ok=True,
            agentId=agent_id,
            ready=False,
            refreshed=True,
            reason="runtime_owner_not_ready",
        )


def _install_openclaw_client(
    client: TestClient,
    openclaw_client: RecordingOpenClawClient,
) -> None:
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: openclaw_client
    )


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


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _run_async(awaitable):
    return asyncio.run(awaitable)


def _parse_sse_events(text: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in text.strip().split("\n\n"):
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            if line.startswith("data: "):
                data = line.removeprefix("data: ")
        events.append((event_name, json.loads(data)))
    return events


def _stored_agent(db_session: Session, user_id: str) -> UserAgent:
    return db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user_id))
    ).scalar_one()


def _set_agent(
    db_session: Session,
    user_id: str,
    *,
    agent_id: str | None,
    provision_status: str,
    is_deleted: bool = False,
) -> None:
    user_agent = _stored_agent(db_session, user_id)
    user_agent.agent_id = agent_id
    user_agent.provision_status = provision_status
    user_agent.is_deleted = is_deleted
    db_session.commit()


def test_chat_success_uses_current_users_ready_agent(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="chat_success", phone="13800138201")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-123",
        provision_status="ready",
    )
    token = _login(client, username="chat_success")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["detail"] == "chat success"
    assert result["data"] == {"answer": "知识库回答"}
    assert openclaw_client.chat_calls == [
        ("web-user-123", str(user["id"]), "你好")
    ]
    assert TEST_TOKEN not in str(result)


def test_chat_stream_false_keeps_sync_response_structure(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="chat_stream_false", phone="13800138401")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-stream-false",
        provision_status="ready",
    )
    token = _login(client, username="chat_stream_false")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好", "stream": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "msg": "success",
        "detail": "chat success",
        "data": {"answer": "知识库回答"},
    }
    assert openclaw_client.chat_calls == [
        ("web-user-stream-false", str(user["id"]), "你好")
    ]
    assert openclaw_client.stream_calls == []


def test_chat_stream_true_returns_sse_start_delta_done_and_cleans_record(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient(
        stream_deltas=["第一段", "第二段"],
    )
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="chat_stream_true", phone="13800138402")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-stream",
        provision_status="ready",
    )
    token = _login(client, username="chat_stream_true")
    active_before = _run_async(chat_stream_manager.active_count())

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好", "stream": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = _parse_sse_events(response.text)
    assert [event for event, _data in events] == [
        "start",
        "delta",
        "delta",
        "done",
    ]
    request_id = events[0][1]["request_id"]
    assert isinstance(request_id, str)
    assert all(data["request_id"] == request_id for _event, data in events)
    assert events[1][1]["content"] == "第一段"
    assert events[2][1]["content"] == "第二段"
    assert events[3][1]["finish_reason"] == "stop"
    assert openclaw_client.stream_calls == [
        ("web-user-stream", str(user["id"]), "你好")
    ]
    assert _run_async(chat_stream_manager.active_count()) == active_before


def test_chat_stream_partial_output_then_error_event(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient(
        stream_deltas=["部分内容"],
        stream_exc=OpenClawConnectionError("connect failed"),
    )
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="chat_stream_error", phone="13800138403")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-stream-error",
        provision_status="ready",
    )
    token = _login(client, username="chat_stream_error")
    active_before = _run_async(chat_stream_manager.active_count())

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好", "stream": True},
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert [event for event, _data in events] == [
        "start",
        "delta",
        "error",
    ]
    assert events[1][1]["content"] == "部分内容"
    assert events[2][1]["code"] == "OPENCLAW_STREAM_ERROR"
    assert events[2][1]["message"] == "OpenClaw 服务不可用"
    assert TEST_TOKEN not in response.text
    assert _run_async(chat_stream_manager.active_count()) == active_before


def test_chat_requires_authentication(
    client: TestClient,
    openclaw_calls: list[str],
) -> None:
    response = client.post(CHAT_URL, json={"message": "你好"})

    assert response.status_code == 401
    assert openclaw_calls == []


def test_chat_cancel_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/chat/request-id/cancel")

    assert response.status_code == 401


def test_chat_cancel_does_not_reveal_other_users_request(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user_a = _register(client, username="cancel_owner", phone="13800138404")
    user_b = _register(client, username="cancel_other", phone="13800138405")
    token_b = _login(client, username="cancel_other")
    record = _run_async(chat_stream_manager.create(user_id=int(user_a["id"])))

    response = client.post(
        f"/api/chat/{record.request_id}/cancel",
        headers=_authorization(token_b),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "生成请求不存在"
    _run_async(
        chat_stream_manager.finish(
            request_id=record.request_id,
            status=ChatStreamStatus.CANCELLED,
        )
    )


def test_chat_cancel_running_request_is_idempotent(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="cancel_running", phone="13800138406")
    token = _login(client, username="cancel_running")
    record = _run_async(chat_stream_manager.create(user_id=int(user["id"])))

    first = client.post(
        f"/api/chat/{record.request_id}/cancel",
        headers=_authorization(token),
    )
    second = client.post(
        f"/api/chat/{record.request_id}/cancel",
        headers=_authorization(token),
    )

    assert first.status_code == 200
    assert first.json()["data"] == {
        "request_id": record.request_id,
        "status": "cancelling",
    }
    assert second.status_code == 200
    assert second.json()["data"]["status"] == "cancelling"
    _run_async(
        chat_stream_manager.finish(
            request_id=record.request_id,
            status=ChatStreamStatus.CANCELLED,
        )
    )


def test_chat_cancel_completed_request_returns_completed_without_500(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="cancel_completed", phone="13800138407")
    token = _login(client, username="cancel_completed")
    record = _run_async(chat_stream_manager.create(user_id=int(user["id"])))
    _run_async(
        chat_stream_manager.finish(
            request_id=record.request_id,
            status=ChatStreamStatus.COMPLETED,
        )
    )

    response = client.post(
        f"/api/chat/{record.request_id}/cancel",
        headers=_authorization(token),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "request_id": record.request_id,
        "status": "completed",
    }


def test_chat_rejects_client_supplied_agent_id(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="extra_agent", phone="13800138202")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="agent-a",
        provision_status="ready",
    )
    token = _login(client, username="extra_agent")
    openclaw_client.chat_calls.clear()

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好", "agent_id": "agent-b"},
    )

    assert response.status_code == 422
    assert openclaw_client.chat_calls == []


def test_chat_trims_message_before_calling_openclaw(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="trim_msg", phone="13800138203")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-trim",
        provision_status="ready",
    )
    token = _login(client, username="trim_msg")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "  你好  "},
    )

    assert response.status_code == 200
    assert openclaw_client.chat_calls[-1] == (
        "web-user-trim",
        str(user["id"]),
        "你好",
    )


def test_chat_user_isolation_uses_each_callers_own_agent(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user_a = _register(client, username="chat_a", phone="13800138204")
    user_b = _register(client, username="chat_b", phone="13800138205")
    _set_agent(
        db_session,
        str(user_a["id"]),
        agent_id="agent-a",
        provision_status="ready",
    )
    _set_agent(
        db_session,
        str(user_b["id"]),
        agent_id="agent-b",
        provision_status="ready",
    )
    token_a = _login(client, username="chat_a")
    token_b = _login(client, username="chat_b")
    openclaw_client.chat_calls.clear()

    response_a = client.post(
        CHAT_URL,
        headers=_authorization(token_a),
        json={"message": "A 的问题"},
    )
    response_b = client.post(
        CHAT_URL,
        headers=_authorization(token_b),
        json={"message": "B 的问题"},
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert openclaw_client.chat_calls == [
        ("agent-a", str(user_a["id"]), "A 的问题"),
        ("agent-b", str(user_b["id"]), "B 的问题"),
    ]


def test_chat_returns_not_found_when_user_agent_missing(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="no_agent", phone="13800138206")
    db_session.delete(_stored_agent(db_session, str(user["id"])))
    db_session.commit()
    token = _login(client, username="no_agent")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "当前用户 Agent 绑定不存在"
    assert openclaw_client.chat_calls == []


def test_chat_does_not_use_soft_deleted_user_agent(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="deleted_agent", phone="13800138207")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="deleted-agent",
        provision_status="ready",
        is_deleted=True,
    )
    token = _login(client, username="deleted_agent")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    assert response.status_code == 404
    assert openclaw_client.chat_calls == []


def test_chat_ready_agent_requires_agent_id(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="empty_agent", phone="13800138208")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id=None,
        provision_status="ready",
    )
    token = _login(client, username="empty_agent")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    db_session.expire_all()
    user_agent = _stored_agent(db_session, str(user["id"]))
    assert response.status_code == 500
    assert response.json()["detail"] == "Agent 数据状态异常"
    assert openclaw_client.chat_calls == []
    assert user_agent.agent_id is None
    assert user_agent.provision_status == "ready"


def test_chat_rejects_not_ready_agent_statuses(
    client: TestClient,
    db_session: Session,
) -> None:
    cases = [
        ("pending_user", "13800138209", "pending", "Agent 尚未创建完成"),
        (
            "provisioning_user",
            "13800138210",
            "provisioning",
            "Agent 正在创建中，请稍后重试",
        ),
        (
            "failed_user",
            "13800138211",
            "failed",
            "Agent 创建失败，请先重新创建 Agent",
        ),
    ]
    for username, phone, provision_status, detail in cases:
        openclaw_client = RecordingOpenClawClient()
        _install_openclaw_client(client, openclaw_client)
        user = _register(client, username=username, phone=phone)
        _set_agent(
            db_session,
            str(user["id"]),
            agent_id=None,
            provision_status=provision_status,
        )
        token = _login(client, username=username)

        response = client.post(
            CHAT_URL,
            headers=_authorization(token),
            json={"message": "你好"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == detail
        assert openclaw_client.chat_calls == []


def test_chat_registered_agent_checks_readiness_then_chats(
    client: TestClient,
    db_session: Session,
) -> None:
    readiness = AgentRuntimeEnsureReadyResult(
        ok=True,
        agentId="web-user-ready-after-check",
        ready=True,
        refreshed=False,
        retryAfterMs=0,
    )
    openclaw_client = RecordingOpenClawClient(readiness=readiness)
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="readiness_ready", phone="13800138215")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-ready-after-check",
        provision_status="registered",
    )
    token = _login(client, username="readiness_ready")
    openclaw_client.readiness_calls.clear()

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    db_session.expire_all()
    user_agent = _stored_agent(db_session, str(user["id"]))
    assert response.status_code == 200
    assert openclaw_client.readiness_calls == ["web-user-ready-after-check"]
    assert openclaw_client.chat_calls == [
        ("web-user-ready-after-check", str(user["id"]), "你好")
    ]
    assert user_agent.provision_status == "ready"
    assert user_agent.provision_error is None


def test_chat_registered_agent_returns_503_when_readiness_not_ready(
    client: TestClient,
    db_session: Session,
) -> None:
    readiness = AgentRuntimeEnsureReadyResult(
        ok=True,
        agentId="web-user-still-warming",
        ready=False,
        refreshed=True,
        reason="runtime_owner_not_ready",
        retryAfterMs=3000,
    )
    openclaw_client = RecordingOpenClawClient(readiness=readiness)
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="readiness_warming", phone="13800138216")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-still-warming",
        provision_status="registered",
    )
    token = _login(client, username="readiness_warming")
    openclaw_client.readiness_calls.clear()

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    db_session.expire_all()
    user_agent = _stored_agent(db_session, str(user["id"]))
    result = response.json()
    assert response.status_code == 503
    assert result["detail"] == (
        "Agent is registered but OpenClaw runtime is still warming up"
    )
    assert result["data"]["provision_status"] == "warming"
    assert result["data"]["retry_after_ms"] == 3000
    assert result["data"]["reason"] == "runtime_owner_not_ready"
    assert result["data"]["refreshed"] is True
    assert openclaw_client.readiness_calls == ["web-user-still-warming"]
    assert openclaw_client.chat_calls == []
    assert user_agent.provision_status == "warming"
    assert user_agent.provision_error == "runtime_owner_not_ready"


def test_chat_runtime_owner_error_marks_agent_warming(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient(
        OpenClawRuntimeNotReadyError("runtime owner missing")
    )
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="runtime_owner", phone="13800138217")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-runtime-owner",
        provision_status="ready",
    )
    token = _login(client, username="runtime_owner")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "你好"},
    )

    db_session.expire_all()
    user_agent = _stored_agent(db_session, str(user["id"]))
    result = response.json()
    assert response.status_code == 503
    assert result["detail"] == (
        "Agent runtime is not ready yet, please retry later"
    )
    assert result["data"]["provision_status"] == "warming"
    assert user_agent.provision_status == "warming"
    assert user_agent.provision_error == "runtime_owner_not_ready"


def test_chat_rejects_empty_messages(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="empty_msg", phone="13800138212")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-empty",
        provision_status="ready",
    )
    token = _login(client, username="empty_msg")

    for message in ("", " ", "\n\t"):
        response = client.post(
            CHAT_URL,
            headers=_authorization(token),
            json={"message": message},
        )
        assert response.status_code == 422

    assert openclaw_client.chat_calls == []


def test_chat_rejects_overlong_message(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="long_msg", phone="13800138213")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-long",
        provision_status="ready",
    )
    token = _login(client, username="long_msg")

    response = client.post(
        CHAT_URL,
        headers=_authorization(token),
        json={"message": "a" * 10001},
    )

    assert response.status_code == 422
    assert openclaw_client.chat_calls == []


def test_chat_accepts_chinese_english_newline_and_unicode(
    client: TestClient,
    db_session: Session,
) -> None:
    openclaw_client = RecordingOpenClawClient()
    _install_openclaw_client(client, openclaw_client)
    user = _register(client, username="unicode_msg", phone="13800138214")
    _set_agent(
        db_session,
        str(user["id"]),
        agent_id="web-user-unicode",
        provision_status="ready",
    )
    token = _login(client, username="unicode_msg")
    messages = ["你好", "hello", "第一行\nsecond line", "普通 Unicode 文本"]

    for message in messages:
        response = client.post(
            CHAT_URL,
            headers=_authorization(token),
            json={"message": message},
        )
        assert response.status_code == 200

    assert openclaw_client.chat_calls == [
        ("web-user-unicode", str(user["id"]), message)
        for message in messages
    ]


def test_chat_openclaw_errors_are_safe_and_do_not_mutate_agent(
    client: TestClient,
    db_session: Session,
) -> None:
    cases = [
        (
            OpenClawTimeoutError(f"timeout {TEST_TOKEN}"),
            504,
            "后端等待 OpenClaw 响应超时，请稍后重试",
        ),
        (
            OpenClawConnectionError("connect failed"),
            503,
            "OpenClaw 服务不可用",
        ),
        (
            OpenClawAuthenticationError(
                f"Authorization: Bearer {TEST_TOKEN}"
            ),
            502,
            "OpenClaw 服务鉴权失败",
        ),
        (
            OpenClawRequestError("bad request"),
            502,
            "上游请求错误",
        ),
        (
            OpenClawConflictError("conflict"),
            409,
            "Agent 当前不可用或上游状态冲突",
        ),
        (
            OpenClawResponseError("OpenClaw Agent or endpoint not found"),
            502,
            "Agent 当前不可用或上游资源不存在",
        ),
        (
            OpenClawResponseError("OpenClaw chat request was rate limited"),
            429,
            "OpenClaw 服务繁忙，请稍后重试",
        ),
        (
            OpenClawResponseError("OpenClaw chat failed with HTTP 500"),
            502,
            "OpenClaw 服务异常",
        ),
    ]
    for index, (exc, expected_status, expected_detail) in enumerate(cases):
        username = f"upstream_{index}"
        phone = f"138001383{index:02d}"
        openclaw_client = RecordingOpenClawClient(exc)
        _install_openclaw_client(client, openclaw_client)
        user = _register(client, username=username, phone=phone)
        _set_agent(
            db_session,
            str(user["id"]),
            agent_id=f"web-user-upstream-{index}",
            provision_status="ready",
        )
        token = _login(client, username=username)

        response = client.post(
            CHAT_URL,
            headers=_authorization(token),
            json={"message": "你好"},
        )

        db_session.expire_all()
        user_agent = _stored_agent(db_session, str(user["id"]))
        assert response.status_code == expected_status
        assert response.json()["detail"] == expected_detail
        assert openclaw_client.chat_calls == [
            (f"web-user-upstream-{index}", str(user["id"]), "你好")
        ]
        assert user_agent.provision_status == "ready"
        assert user_agent.agent_id == f"web-user-upstream-{index}"
        assert TEST_TOKEN not in str(response.json())
        assert "Authorization" not in str(response.json())
