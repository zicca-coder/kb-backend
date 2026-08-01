import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-jwt-secret-key-with-sufficient-length",
)

from app.core.database import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.api.dependencies import get_openclaw_client  # noqa: E402
from app.schemas.openclaw import (  # noqa: E402
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
)

TEST_SCHEMA = """
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    phone VARCHAR(32) UNIQUE,
    display_name VARCHAR(128) NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    created_by VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(64) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

USER_AGENT_SCHEMA = """
CREATE TABLE user_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id BIGINT NOT NULL UNIQUE,
    agent_id VARCHAR(128) UNIQUE,
    runtime_type VARCHAR(32) NOT NULL DEFAULT 'shared',
    runtime_id VARCHAR(255),
    provision_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    provision_error VARCHAR(1000),
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    created_by VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(64) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""

CONVERSATION_SCHEMA = """
CREATE TABLE conversations (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    title VARCHAR(100) NOT NULL DEFAULT '新对话',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    last_message_at DATETIME,
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    created_by VARCHAR(64) NOT NULL DEFAULT 'system',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(64) NOT NULL DEFAULT 'system',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""

CONVERSATION_MESSAGE_SCHEMA = """
CREATE TABLE conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id VARCHAR(36) NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    request_id VARCHAR(36),
    sequence_no INTEGER NOT NULL,
    error_message VARCHAR(1000),
    created_by VARCHAR(64) NOT NULL DEFAULT 'system',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(64) NOT NULL DEFAULT 'system',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    UNIQUE (conversation_id, sequence_no)
)
"""


@pytest.fixture(scope="session")
def test_database_path(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("database") / "auth_test.sqlite3"


@pytest.fixture(scope="session")
def test_engine(test_database_path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{test_database_path.as_posix()}",
    )
    with engine.begin() as connection:
        connection.execute(text(TEST_SCHEMA))
        connection.execute(text(USER_AGENT_SCHEMA))
        connection.execute(text(CONVERSATION_SCHEMA))
        connection.execute(text(CONVERSATION_MESSAGE_SCHEMA))
        connection.execute(
            text(
                "CREATE INDEX ix_conversations_user_deleted_last_message "
                "ON conversations (user_id, is_deleted, last_message_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_conversation_messages_conversation_sequence "
                "ON conversation_messages (conversation_id, sequence_no)"
            )
        )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def async_session_factory(
    test_database_path: Path,
    test_engine,
) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{test_database_path.as_posix()}",
        poolclass=NullPool,
    )
    factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        asyncio.run(async_engine.dispose())


@pytest.fixture(autouse=True)
def clean_database(test_engine) -> Generator[None, None, None]:
    with test_engine.begin() as connection:
        connection.execute(text("DELETE FROM conversation_messages"))
        connection.execute(text("DELETE FROM conversations"))
        connection.execute(text("DELETE FROM user_agents"))
        connection.execute(text("DELETE FROM users"))
    yield
    with test_engine.begin() as connection:
        connection.execute(text("DELETE FROM conversation_messages"))
        connection.execute(text("DELETE FROM conversations"))
        connection.execute(text("DELETE FROM user_agents"))
        connection.execute(text("DELETE FROM users"))


@pytest.fixture
def db_session(
    test_engine,
    clean_database,
) -> Generator[Session, None, None]:
    factory = sessionmaker(
        bind=test_engine,
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def openclaw_calls() -> list[str]:
    return []


@pytest.fixture
def client(
    async_session_factory: async_sessionmaker[AsyncSession],
    openclaw_calls: list[str],
) -> Generator[TestClient, None, None]:
    application = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with async_session_factory() as session:
            yield session

    class FakeOpenClawClient:
        async def provision_agent(
            self,
            *,
            external_user_id: int | str,
        ) -> AgentProvisionResult:
            normalized = str(external_user_id)
            openclaw_calls.append(normalized)
            return AgentProvisionResult(
                agent_id=f"web-user-{normalized}",
            )

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

        async def stream_chat_completion(
            self,
            *,
            agent_id: str,
            openclaw_user: str,
            message: str,
            session_key: str | None = None,
        ) -> AsyncIterator[str]:
            yield "测试回答"

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_openclaw_client] = (
        lambda: FakeOpenClawClient()
    )
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
