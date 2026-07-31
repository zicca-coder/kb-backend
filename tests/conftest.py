import asyncio
import os
from collections.abc import AsyncGenerator, Generator
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
    provision_status VARCHAR(32) NOT NULL DEFAULT 'creating',
    provision_error VARCHAR(1000),
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    created_by VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(64) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
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
        connection.execute(text("DELETE FROM user_agents"))
        connection.execute(text("DELETE FROM users"))
    yield
    with test_engine.begin() as connection:
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
def client(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> Generator[TestClient, None, None]:
    application = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with async_session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
