from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_openclaw_client
from app.core.errors import (
    OpenClawAuthenticationError,
    OpenClawConnectionError,
    OpenClawResponseError,
    OpenClawTimeoutError,
)
from app.models.user import User
from app.models.user_agent import UserAgent
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
)

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
MY_USER_AGENT_URL = "/api/user-agents/me"
PROVISION_URL = "/api/user-agents/me/provision"
PASSWORD = "Kb@123456"
TEST_TOKEN = "secret-gateway-token"


class FailingOpenClawClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[str] = []

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        self.calls.append(str(external_user_id))
        raise self.exc

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        raise AssertionError("runtime readiness should not be checked")


class RecordingOpenClawClient:
    def __init__(
        self,
        readiness: AgentRuntimeEnsureReadyResult | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.readiness_calls: list[str] = []
        self.readiness = readiness

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        normalized = str(external_user_id)
        self.calls.append(normalized)
        return AgentProvisionResult(agent_id=f"web-user-{normalized}")

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        self.readiness_calls.append(agent_id)
        return self.readiness or AgentRuntimeEnsureReadyResult(
            ok=True,
            agentId=agent_id,
            ready=True,
            refreshed=True,
            retryAfterMs=0,
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


def _stored_agent(db_session: Session, user_id: str) -> UserAgent:
    return db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user_id))
    ).scalar_one()


def _set_failed_agent(db_session: Session, user_id: str) -> None:
    user_agent = _stored_agent(db_session, user_id)
    user_agent.agent_id = None
    user_agent.provision_status = "failed"
    user_agent.provision_error = "Backend timed out while waiting for OpenClaw"
    db_session.commit()


def test_register_auto_provisions_with_string_external_user_id(
    client: TestClient,
    db_session: Session,
    openclaw_calls: list[str],
) -> None:
    created = _register(
        client,
        username="auto_success",
        phone="13800138101",
    )

    user_agent = _stored_agent(db_session, str(created["id"]))

    assert openclaw_calls == [created["id"]]
    assert isinstance(openclaw_calls[0], str)
    assert user_agent.agent_id == f"web-user-{created['id']}"
    assert user_agent.provision_status == "ready"
    assert user_agent.provision_error is None
    assert created["agent"]["provision_status"] == "ready"
    assert created["agent"]["agent_ready"] is True
    assert created["agent"]["retry_after_ms"] is None
    assert isinstance(created["id"], str)


def test_register_marks_agent_warming_when_runtime_not_ready(
    client: TestClient,
    db_session: Session,
) -> None:
    readiness = AgentRuntimeEnsureReadyResult(
        ok=True,
        agentId="web-user-placeholder",
        ready=False,
        refreshed=True,
        reason="runtime_owner_not_ready",
        retryAfterMs=3000,
    )
    recording_client = RecordingOpenClawClient(readiness=readiness)
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: recording_client
    )

    created = _register(
        client,
        username="runtime_warming",
        phone="13800138112",
    )

    user_agent = _stored_agent(db_session, str(created["id"]))
    assert recording_client.calls == [created["id"]]
    assert recording_client.readiness_calls == [
        f"web-user-{created['id']}"
    ]
    assert user_agent.agent_id == f"web-user-{created['id']}"
    assert user_agent.provision_status == "warming"
    assert user_agent.provision_error == "runtime_owner_not_ready"
    assert created["agent"]["provision_status"] == "warming"
    assert created["agent"]["agent_ready"] is False
    assert created["agent"]["retry_after_ms"] == 3000


def test_register_keeps_user_when_openclaw_times_out(
    client: TestClient,
    db_session: Session,
) -> None:
    failing_client = FailingOpenClawClient(
        OpenClawTimeoutError(f"timeout with {TEST_TOKEN}")
    )
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: failing_client
    )

    created = _register(
        client,
        username="timeout_user",
        phone="13800138102",
    )
    user = db_session.get(User, int(created["id"]))
    user_agent = _stored_agent(db_session, str(created["id"]))

    assert user is not None
    assert user_agent.agent_id is None
    assert user_agent.provision_status == "failed"
    assert user_agent.provision_error == (
        "Backend timed out while waiting for OpenClaw"
    )
    assert created["agent"]["agent_id"] is None
    assert created["agent"]["provision_status"] == "failed"
    assert TEST_TOKEN not in str(created)


def test_register_keeps_user_when_openclaw_connection_fails(
    client: TestClient,
    db_session: Session,
) -> None:
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: FailingOpenClawClient(
            OpenClawConnectionError("connect failed")
        )
    )

    created = _register(
        client,
        username="connection_user",
        phone="13800138103",
    )
    user_agent = _stored_agent(db_session, str(created["id"]))

    assert db_session.get(User, int(created["id"])) is not None
    assert user_agent.agent_id is None
    assert user_agent.provision_status == "failed"
    assert user_agent.provision_error == "OpenClaw connection failed"


def test_register_authentication_failure_does_not_leak_token(
    client: TestClient,
    db_session: Session,
) -> None:
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: FailingOpenClawClient(
            OpenClawAuthenticationError(
                f"Authorization: Bearer {TEST_TOKEN}"
            )
        )
    )

    created = _register(
        client,
        username="auth_failure_user",
        phone="13800138104",
    )
    user_agent = _stored_agent(db_session, str(created["id"]))

    assert user_agent.provision_status == "failed"
    assert user_agent.provision_error == "OpenClaw authentication failed"
    assert TEST_TOKEN not in str(created)
    assert "Authorization" not in str(created)


def test_register_invalid_openclaw_response_marks_failed(
    client: TestClient,
    db_session: Session,
) -> None:
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: FailingOpenClawClient(
            OpenClawResponseError("invalid payload")
        )
    )

    created = _register(
        client,
        username="invalid_response_user",
        phone="13800138105",
    )
    user_agent = _stored_agent(db_session, str(created["id"]))

    assert user_agent.agent_id is None
    assert user_agent.provision_status == "failed"
    assert user_agent.provision_error == "OpenClaw returned invalid response"


def test_manual_retry_from_failed_succeeds(
    client: TestClient,
    db_session: Session,
) -> None:
    created = _register(
        client,
        username="manual_retry",
        phone="13800138106",
    )
    _set_failed_agent(db_session, str(created["id"]))
    token = _login(client, username="manual_retry")
    recording_client = RecordingOpenClawClient()
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: recording_client
    )

    response = client.post(
        PROVISION_URL,
        headers=_authorization(token),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    db_session.expire_all()
    user_agent = _stored_agent(db_session, str(created["id"]))
    assert recording_client.calls == [created["id"]]
    assert recording_client.readiness_calls == [
        f"web-user-{created['id']}"
    ]
    assert result["agent_id"] == f"web-user-{created['id']}"
    assert result["provision_status"] == "ready"
    assert result["agent_ready"] is True
    assert user_agent.agent_id == f"web-user-{created['id']}"
    assert user_agent.provision_status == "ready"
    assert user_agent.provision_error is None


def test_registered_manual_retry_is_idempotent(
    client: TestClient,
    openclaw_calls: list[str],
) -> None:
    created = _register(
        client,
        username="ready_retry",
        phone="13800138107",
    )
    token = _login(client, username="ready_retry")
    openclaw_calls.clear()

    response = client.post(
        PROVISION_URL,
        headers=_authorization(token),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert openclaw_calls == []
    assert result["agent_id"] == f"web-user-{created['id']}"
    assert result["provision_status"] == "ready"


def test_provisioning_manual_retry_is_rejected(
    client: TestClient,
    db_session: Session,
    openclaw_calls: list[str],
) -> None:
    created = _register(
        client,
        username="busy_retry",
        phone="13800138108",
    )
    user_agent = _stored_agent(db_session, str(created["id"]))
    user_agent.agent_id = None
    user_agent.provision_status = "provisioning"
    db_session.commit()
    token = _login(client, username="busy_retry")
    openclaw_calls.clear()

    response = client.post(
        PROVISION_URL,
        headers=_authorization(token),
    )

    db_session.expire_all()
    user_agent = _stored_agent(db_session, str(created["id"]))
    assert response.status_code == 409
    assert openclaw_calls == []
    assert user_agent.provision_status == "provisioning"


def test_manual_provision_requires_authentication(
    client: TestClient,
) -> None:
    response = client.post(PROVISION_URL)

    assert response.status_code == 401


def test_manual_provision_uses_current_user_only(
    client: TestClient,
    db_session: Session,
) -> None:
    user_a = _register(
        client,
        username="isolated_a",
        phone="13800138109",
    )
    user_b = _register(
        client,
        username="isolated_b",
        phone="13800138110",
    )
    _set_failed_agent(db_session, str(user_a["id"]))
    _set_failed_agent(db_session, str(user_b["id"]))
    token_a = _login(client, username="isolated_a")
    recording_client = RecordingOpenClawClient()
    client.app.dependency_overrides[get_openclaw_client] = (
        lambda: recording_client
    )

    response = client.post(
        PROVISION_URL,
        headers=_authorization(token_a),
        json={"user_id": user_b["id"]},
    )

    db_session.expire_all()
    agent_a = _stored_agent(db_session, str(user_a["id"]))
    agent_b = _stored_agent(db_session, str(user_b["id"]))
    assert response.status_code == 200
    assert recording_client.calls == [user_a["id"]]
    assert recording_client.readiness_calls == [
        f"web-user-{user_a['id']}"
    ]
    assert agent_a.provision_status == "ready"
    assert agent_b.provision_status == "failed"


def test_get_my_user_agent_returns_safe_provision_error(
    client: TestClient,
    db_session: Session,
) -> None:
    created = _register(
        client,
        username="safe_error",
        phone="13800138111",
    )
    _set_failed_agent(db_session, str(created["id"]))
    token = _login(client, username="safe_error")

    response = client.get(
        MY_USER_AGENT_URL,
        headers=_authorization(token),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["provision_status"] == "failed"
    assert result["provision_error"] != (
        "Backend timed out while waiting for OpenClaw"
    )
    assert TEST_TOKEN not in str(result)
