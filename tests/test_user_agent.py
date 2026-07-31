from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user_agent import UserAgent

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
MY_USER_AGENT_URL = "/api/user-agents/me"
PASSWORD = "Kb@123456"


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


def test_get_my_user_agent_returns_current_users_binding(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _register(
        client,
        username="user_a",
        phone="13800138001",
    )
    token = _login(client, username="user_a")
    stored = db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user["id"]))
    ).scalar_one()

    response = client.get(
        MY_USER_AGENT_URL,
        headers=_authorization(token),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["id"] == stored.id
    assert result["user_id"] == user["id"]
    assert isinstance(result["user_id"], str)
    assert result["provision_status"] == stored.provision_status
    assert result["agent_id"] == stored.agent_id
    assert "workspace_path" not in result
    assert "agent_dir" not in result


def test_get_my_user_agent_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get(MY_USER_AGENT_URL)

    assert response.status_code == 401


def test_get_my_user_agent_never_returns_another_users_binding(
    client: TestClient,
    db_session: Session,
) -> None:
    user_a = _register(
        client,
        username="user_a",
        phone="13800138001",
    )
    user_b = _register(
        client,
        username="user_b",
        phone="13800138002",
    )
    token_a = _login(client, username="user_a")
    user_b_agent = db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user_b["id"]))
    ).scalar_one()

    response = client.get(
        MY_USER_AGENT_URL,
        headers=_authorization(token_a),
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["user_id"] == user_a["id"]
    assert result["user_id"] != user_b["id"]
    assert result["id"] != user_b_agent.id


def test_get_my_user_agent_returns_404_when_binding_is_missing(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _register(
        client,
        username="without_agent",
        phone="13800138003",
    )
    token = _login(client, username="without_agent")
    user_agent = db_session.execute(
        select(UserAgent).where(UserAgent.user_id == int(user["id"]))
    ).scalar_one()
    db_session.delete(user_agent)
    db_session.commit()

    response = client.get(
        MY_USER_AGENT_URL,
        headers=_authorization(token),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User agent not found"
