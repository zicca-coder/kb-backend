import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
import pytest

from app.clients.openclaw_client import OpenClawClient, PROVISION_PATH
from app.core.errors import (
    OpenClawAuthenticationError,
    OpenClawConfigurationError,
    OpenClawConflictError,
    OpenClawConnectionError,
    OpenClawRequestError,
    OpenClawResponseError,
    OpenClawTimeoutError,
)
from app.schemas.openclaw import AgentProvisionResult

T = TypeVar("T")
TEST_TOKEN = "super-secret-test-token"
SNOWFLAKE_ID = "2038429384729382912"


def run_async(awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


def provision_response() -> dict[str, str]:
    return {"agent_id": f"web-user-{SNOWFLAKE_ID}"}


def make_async_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://openclaw.test",
    )


def make_openclaw_client(
    http_client: httpx.AsyncClient,
    *,
    token: str = TEST_TOKEN,
) -> OpenClawClient:
    return OpenClawClient(
        base_url="http://openclaw.test/",
        gateway_token=token,
        timeout_seconds=20,
        http_client=http_client,
    )


@pytest.mark.parametrize("status_code", [200, 201])
def test_provision_agent_parses_minimal_success_response(
    status_code: int,
) -> None:
    async def scenario() -> AgentProvisionResult:
        async with make_async_client(
            lambda _request: httpx.Response(
                status_code,
                json=provision_response(),
            ),
        ) as http_client:
            return await make_openclaw_client(http_client).provision_agent(
                external_user_id=SNOWFLAKE_ID,
            )

    result = run_async(scenario())

    assert isinstance(result, AgentProvisionResult)
    assert result.agent_id == f"web-user-{SNOWFLAKE_ID}"


def test_provision_agent_request_format_preserves_large_id() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(201, json=provision_response())

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            await make_openclaw_client(http_client).provision_agent(
                external_user_id=int(SNOWFLAKE_ID),
            )

    run_async(scenario())

    assert len(seen_requests) == 1
    request = seen_requests[0]
    body = json.loads(request.content.decode())
    assert request.method == "POST"
    assert request.url.path == PROVISION_PATH
    assert request.headers["content-type"] == "application/json"
    assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
    assert body == {"external_user_id": SNOWFLAKE_ID}
    assert isinstance(body["external_user_id"], str)
    assert set(body) == {"external_user_id"}


def test_provision_agent_treats_conflict_with_agent_id_as_success() -> None:
    async def scenario() -> AgentProvisionResult:
        async with make_async_client(
            lambda _request: httpx.Response(
                409,
                json=provision_response(),
            ),
        ) as http_client:
            return await make_openclaw_client(http_client).provision_agent(
                external_user_id=SNOWFLAKE_ID,
            )

    result = run_async(scenario())

    assert result.agent_id == f"web-user-{SNOWFLAKE_ID}"


def test_provision_agent_ignores_extra_openclaw_response_fields() -> None:
    async def scenario() -> AgentProvisionResult:
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                json={
                    "created": False,
                    "agent_id": f"web-user-{SNOWFLAKE_ID}",
                    "workspace_path": "/sensitive/workspace",
                    "agent_dir": "/sensitive/agent",
                    "workspace_created": False,
                    "agent_dir_created": False,
                    "agent_registered": False,
                    "template_files": [
                        {"file_name": "AGENTS.md", "status": "skipped"},
                    ],
                },
            ),
        ) as http_client:
            return await make_openclaw_client(http_client).provision_agent(
                external_user_id=SNOWFLAKE_ID,
            )

    result = run_async(scenario())

    assert result.agent_id == f"web-user-{SNOWFLAKE_ID}"
    assert not hasattr(result, "workspace_path")
    assert not hasattr(result, "agent_dir")


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, OpenClawAuthenticationError),
        (403, OpenClawAuthenticationError),
        (409, OpenClawConflictError),
        (400, OpenClawRequestError),
        (413, OpenClawRequestError),
        (500, OpenClawResponseError),
    ],
)
def test_provision_agent_maps_http_errors(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(
                status_code,
                json={"detail": "secret"},
            ),
        ) as http_client:
            client = make_openclaw_client(http_client)
            with pytest.raises(expected_error) as exc_info:
                await client.provision_agent(external_user_id=SNOWFLAKE_ID)
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())


@pytest.mark.parametrize("response", [{}, {"agent_id": None}, {"detail": "exists"}])
def test_provision_agent_conflict_without_agent_id_remains_conflict(
    response: dict[str, object],
) -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(409, json=response),
        ) as http_client:
            with pytest.raises(OpenClawConflictError):
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )

    run_async(scenario())


def test_provision_agent_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawTimeoutError) as exc_info:
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())


def test_provision_agent_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawConnectionError) as exc_info:
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())


def test_provision_agent_rejects_invalid_json() -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(201, content=b"not-json"),
        ) as http_client:
            with pytest.raises(OpenClawResponseError):
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )

    run_async(scenario())


@pytest.mark.parametrize("response", [{}, {"agent_id": ""}, {"agent_id": "   "}])
def test_provision_agent_rejects_missing_or_empty_agent_id(
    response: dict[str, str],
) -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(201, json=response),
        ) as http_client:
            with pytest.raises(OpenClawResponseError):
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )

    run_async(scenario())


@pytest.mark.parametrize(
    "external_user_id",
    [
        None,
        "",
        "   ",
        0,
        -1,
        1.5,
        True,
        False,
        "00123",
        "+123",
        "-123",
        "1.5",
        "abc",
    ],
)
def test_provision_agent_rejects_invalid_input_without_http_request(
    external_user_id: object,
) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201, json=provision_response())

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            client = make_openclaw_client(http_client)
            with pytest.raises(OpenClawRequestError):
                await client.provision_agent(external_user_id=external_user_id)  # type: ignore[arg-type]

    run_async(scenario())

    assert called is False


def test_empty_gateway_token_fails_before_http_request() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201, json=provision_response())

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawConfigurationError) as exc_info:
                make_openclaw_client(http_client, token="")
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())

    assert called is False


@pytest.mark.parametrize("status_code", [401, 500])
def test_sensitive_token_not_in_exceptions_or_logs(
    status_code: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(
                status_code,
                json={"detail": TEST_TOKEN},
            ),
        ) as http_client:
            with pytest.raises(
                (OpenClawAuthenticationError, OpenClawResponseError),
            ) as exc_info:
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())

    assert TEST_TOKEN not in caplog.text
    assert "workspace" not in caplog.text
    assert "agent_dir" not in caplog.text


def test_sensitive_token_not_in_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(TEST_TOKEN, request=request)

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawConnectionError) as exc_info:
                await make_openclaw_client(http_client).provision_agent(
                    external_user_id=SNOWFLAKE_ID,
                )
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())
