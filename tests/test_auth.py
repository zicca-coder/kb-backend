from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.core.settings import settings
from app.models.user import User
from app.models.user_agent import UserAgent
from app.repository.user_agent_repository import UserAgentRepository

REGISTER_URL = "/api/auth/register"
LOGIN_URL = "/api/auth/login"
ME_URL = "/api/auth/me"
PASSWORD = "Kb@123456"
JS_SAFE_INTEGER_MAX = 2**53 - 1


def _register(
    client: TestClient,
    *,
    username: str = "leeziqiang",
    phone: str | None = "13800138000",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "username": username,
        "password": PASSWORD,
        "display_name": "李自强",
        "email": f"{username}@example.com",
    }
    if phone is not None:
        payload["phone"] = phone
    response = client.post(REGISTER_URL, json=payload)
    assert response.status_code == 200
    return response.json()["data"]


def _login(
    client: TestClient,
    *,
    account: str = "leeziqiang",
    password: str = PASSWORD,
):
    return client.post(
        LOGIN_URL,
        json={"account": account, "password": password},
    )


def test_register_hashes_password_and_hides_sensitive_fields(
    client: TestClient,
    db_session: Session,
    openclaw_calls: list[str],
) -> None:
    created = _register(client)

    assert created["username"] == "leeziqiang"
    assert created["phone"] == "13800138000"
    assert created["email"] == "leeziqiang@example.com"
    assert isinstance(created["id"], str)
    assert created["id"].isdecimal()
    assert int(created["id"]) > JS_SAFE_INTEGER_MAX
    assert "password" not in created
    assert "password_hash" not in created
    assert created["agent"]["agent_id"] == f"web-user-{created['id']}"
    assert created["agent"]["provision_status"] == "ready"
    assert created["agent"]["agent_ready"] is True
    assert created["agent"]["retry_after_ms"] is None

    user = db_session.execute(
        select(User).where(User.id == int(created["id"]))
    ).scalar_one()
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$argon2")
    assert verify_password(PASSWORD, user.password_hash)
    assert user.created_by == "leeziqiang"
    assert user.updated_by == "leeziqiang"

    user_agents = db_session.execute(
        select(UserAgent).where(UserAgent.user_id == user.id)
    ).scalars().all()
    assert len(user_agents) == 1
    assert user_agents[0].user_id == user.id
    assert user_agents[0].provision_status == "ready"
    assert user_agents[0].agent_id == f"web-user-{created['id']}"
    assert user_agents[0].provision_error is None
    assert openclaw_calls == [created["id"]]


def test_register_rejects_duplicate_username_and_phone(
    client: TestClient,
    db_session: Session,
) -> None:
    _register(client)

    duplicate_username = client.post(
        REGISTER_URL,
        json={
            "username": "leeziqiang",
            "password": PASSWORD,
            "display_name": "重复用户名",
            "phone": "13900139000",
        },
    )
    assert duplicate_username.status_code == 409
    assert duplicate_username.json()["detail"] == "用户名已存在"

    duplicate_phone = client.post(
        REGISTER_URL,
        json={
            "username": "another",
            "password": PASSWORD,
            "display_name": "重复手机号",
            "phone": "13800138000",
        },
    )
    assert duplicate_phone.status_code == 409
    assert duplicate_phone.json()["detail"] == "手机号已存在"
    assert db_session.scalar(select(func.count(User.id))) == 1
    assert db_session.scalar(select(func.count(UserAgent.id))) == 1


def test_register_generates_unique_snowflake_id_and_reuses_it_for_user_agent(
    client: TestClient,
    db_session: Session,
    openclaw_calls: list[str],
) -> None:
    first = _register(
        client,
        username="snowflake_a",
        phone="13800138011",
    )
    second = _register(
        client,
        username="snowflake_b",
        phone="13800138012",
    )

    assert first["id"] != second["id"]
    assert int(first["id"]) > JS_SAFE_INTEGER_MAX
    assert int(second["id"]) > JS_SAFE_INTEGER_MAX

    first_user = db_session.get(User, int(first["id"]))
    assert first_user is not None
    first_agent = db_session.execute(
        select(UserAgent).where(UserAgent.user_id == first_user.id)
    ).scalar_one()
    assert first_agent.user_id == first_user.id
    assert first_agent.agent_id == f"web-user-{first['id']}"
    assert openclaw_calls == [first["id"], second["id"]]


def test_register_rolls_back_user_when_user_agent_creation_fails(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_to_create_user_agent(
        self: UserAgentRepository,
        user_agent: UserAgent,
    ) -> UserAgent:
        raise RuntimeError("simulated user agent creation failure")

    monkeypatch.setattr(
        UserAgentRepository,
        "create",
        fail_to_create_user_agent,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated user agent creation failure",
    ):
        _register(client)

    db_session.expire_all()
    assert db_session.scalar(select(func.count(User.id))) == 0
    assert db_session.scalar(select(func.count(UserAgent.id))) == 0


def test_register_accepts_null_phone_and_validates_input(
    client: TestClient,
) -> None:
    created = _register(
        client,
        username="without_phone",
        phone=None,
    )
    assert created["phone"] is None

    invalid_username = client.post(
        REGISTER_URL,
        json={
            "username": "bad username",
            "password": PASSWORD,
            "display_name": "Bad",
        },
    )
    short_password = client.post(
        REGISTER_URL,
        json={
            "username": "valid_name",
            "password": "short",
            "display_name": "Bad",
        },
    )
    assert invalid_username.status_code == 422
    assert short_password.status_code == 422


def test_login_supports_username_and_phone(client: TestClient) -> None:
    _register(client)

    for account in ("leeziqiang", "13800138000"):
        response = _login(client, account=account)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 7200
        assert data["access_token"]
        assert data["user"]["username"] == "leeziqiang"
        assert isinstance(data["user"]["id"], str)
        assert data["user"]["id"].isdecimal()


def test_login_failures_have_same_message(
    client: TestClient,
    db_session: Session,
) -> None:
    created = _register(client)

    wrong_password = _login(client, password="wrong-password")
    missing_account = _login(client, account="missing")
    for response in (wrong_password, missing_account):
        assert response.status_code == 401
        assert response.json()["detail"] == "账号或密码错误"
        assert response.headers["www-authenticate"] == "Bearer"

    user = db_session.get(User, int(created["id"]))
    assert user is not None
    user.is_deleted = True
    db_session.commit()

    deleted_user = _login(client)
    assert deleted_user.status_code == 401
    assert deleted_user.json()["detail"] == "账号或密码错误"


def test_me_accepts_valid_token_and_rejects_missing_or_tampered_token(
    client: TestClient,
) -> None:
    _register(client)
    token = _login(client).json()["data"]["access_token"]

    valid = client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert valid.status_code == 200
    assert valid.json()["data"]["username"] == "leeziqiang"
    assert isinstance(valid.json()["data"]["id"], str)
    assert valid.json()["data"]["id"].isdecimal()

    missing = client.get(ME_URL)
    tampered = client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {token}x"},
    )
    assert missing.status_code == 401
    assert tampered.status_code == 401


def test_jwt_sub_is_string_and_preserves_large_id(
    client: TestClient,
) -> None:
    created = _register(client)
    token = _login(client).json()["data"]["access_token"]

    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )

    assert payload["sub"] == created["id"]
    assert isinstance(payload["sub"], str)
    assert int(payload["sub"]) > JS_SAFE_INTEGER_MAX


@pytest.mark.parametrize("subject", ["abc", "-1", "1.5", ""])
def test_me_rejects_invalid_jwt_subject(
    client: TestClient,
    subject: str,
) -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": subject,
            "username": "bad-subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_me_rejects_expired_token_and_deleted_user(
    client: TestClient,
    db_session: Session,
) -> None:
    created = _register(client)
    now = datetime.now(timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": str(created["id"]),
            "username": created["username"],
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    expired = client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert expired.status_code == 401

    token = _login(client).json()["data"]["access_token"]
    user = db_session.get(User, int(created["id"]))
    assert user is not None
    user.is_deleted = True
    db_session.commit()

    deleted = client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 401
