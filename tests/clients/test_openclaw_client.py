import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
import pytest

from app.clients.openclaw_client import (
    ADMIN_RPC_PATH,
    CHAT_COMPLETIONS_PATH,
    ENSURE_AGENT_RUNTIME_READY_METHOD,
    OpenClawClient,
    PROVISION_PATH,
)
from app.core.errors import (
    OpenClawAuthenticationError,
    OpenClawConfigurationError,
    OpenClawConflictError,
    OpenClawConnectionError,
    OpenClawRequestError,
    OpenClawResponseError,
    OpenClawRuntimeNotReadyError,
    OpenClawTimeoutError,
)
from app.schemas.openclaw import (
    AgentProvisionResult,
    AgentRuntimeEnsureReadyResult,
)

T = TypeVar("T")
TEST_TOKEN = "super-secret-test-token"
SNOWFLAKE_ID = "2038429384729382912"


def run_async(awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable)


def provision_response() -> dict[str, str]:
    return {"agent_id": f"web-user-{SNOWFLAKE_ID}"}


def chat_response(answer: str = "回答内容") -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": answer,
                }
            }
        ]
    }


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
        http_client=http_client,
    )


class ChunkedByteStream(httpx.AsyncByteStream):
    def __init__(
        self,
        chunks: list[bytes],
        exc: Exception | None = None,
    ) -> None:
        self.chunks = chunks
        self.exc = exc
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.exc is not None:
            raise self.exc

    async def aclose(self) -> None:
        self.closed = True


def chat_stream_event(content: str) -> bytes:
    payload = {
        "choices": [
            {
                "delta": {
                    "content": content,
                }
            }
        ]
    }
    return (
        "data: "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n\n"
    ).encode()


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
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 120.0,
        "write": 30.0,
        "pool": 10.0,
    }
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


def test_custom_openclaw_timeout_config_is_used_for_requests() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=chat_response())

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            client = OpenClawClient(
                base_url="http://openclaw.test/",
                gateway_token=TEST_TOKEN,
                connect_timeout_seconds=2,
                read_timeout_seconds=120,
                write_timeout_seconds=5,
                pool_timeout_seconds=3,
                http_client=http_client,
            )
            await client.chat_completion(
                agent_id="web-user-123",
                openclaw_user=SNOWFLAKE_ID,
                message="你好",
            )

    run_async(scenario())

    assert seen_requests[0].extensions["timeout"] == {
        "connect": 2.0,
        "read": 120.0,
        "write": 5.0,
        "pool": 3.0,
    }


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


def test_chat_completion_request_format_uses_agent_model_and_user_id() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=chat_response())

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            await make_openclaw_client(http_client).chat_completion(
                agent_id="web-user-123",
                openclaw_user=SNOWFLAKE_ID,
                message="你好",
            )

    run_async(scenario())

    assert len(seen_requests) == 1
    request = seen_requests[0]
    body = json.loads(request.content.decode())
    assert request.method == "POST"
    assert request.url.path == CHAT_COMPLETIONS_PATH
    assert request.headers["content-type"] == "application/json"
    assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 120.0,
        "write": 30.0,
        "pool": 10.0,
    }
    assert body == {
        "model": "openclaw/web-user-123",
        "user": SNOWFLAKE_ID,
        "messages": [{"role": "user", "content": "你好"}],
        "stream": False,
    }
    assert body["user"] != "web-user-123"


def test_chat_completion_sends_explicit_openclaw_session_key() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=chat_response())

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            await make_openclaw_client(http_client).chat_completion(
                agent_id="web-user-123",
                openclaw_user=SNOWFLAKE_ID,
                message="你好",
                session_key="webchat:conv-123",
            )

    run_async(scenario())

    assert seen_requests[0].headers["x-openclaw-session-key"] == (
        "webchat:conv-123"
    )


def test_stream_chat_completion_request_format_and_delta_order() -> None:
    seen_requests: list[httpx.Request] = []
    stream = ChunkedByteStream(
        [
            chat_stream_event("第一段"),
            chat_stream_event(" second"),
            b"data: [DONE]\n\n",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    async def scenario() -> list[str]:
        async with make_async_client(handler) as http_client:
            return [
                delta
                async for delta in make_openclaw_client(
                    http_client
                ).stream_chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                    session_key="webchat:conv-stream-123",
                )
            ]

    assert run_async(scenario()) == ["第一段", " second"]
    assert stream.closed is True
    body = json.loads(seen_requests[0].content.decode())
    assert seen_requests[0].method == "POST"
    assert seen_requests[0].url.path == CHAT_COMPLETIONS_PATH
    assert seen_requests[0].headers["x-openclaw-session-key"] == (
        "webchat:conv-stream-123"
    )
    assert body == {
        "model": "openclaw/web-user-123",
        "user": SNOWFLAKE_ID,
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
    }


def test_stream_chat_completion_handles_utf8_across_chunks() -> None:
    event = chat_stream_event("中文跨 chunk")
    split_at = event.index("文".encode("utf-8"))
    stream = ChunkedByteStream(
        [
            event[:split_at],
            event[split_at:split_at + 1],
            event[split_at + 1:],
            b"data: [DONE]\n\n",
        ]
    )

    async def scenario() -> list[str]:
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            ),
        ) as http_client:
            return [
                delta
                async for delta in make_openclaw_client(
                    http_client
                ).stream_chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )
            ]

    assert run_async(scenario()) == ["中文跨 chunk"]
    assert stream.closed is True


def test_stream_chat_completion_partial_output_then_invalid_event_closes() -> None:
    stream = ChunkedByteStream(
        [
            chat_stream_event("已输出"),
            b"data: {not-json}\n\n",
        ]
    )

    async def scenario() -> list[str]:
        deltas: list[str] = []
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            ),
        ) as http_client:
            with pytest.raises(OpenClawResponseError):
                async for delta in make_openclaw_client(
                    http_client
                ).stream_chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                ):
                    deltas.append(delta)
        return deltas

    assert run_async(scenario()) == ["已输出"]
    assert stream.closed is True


def test_stream_chat_completion_cancel_closes_upstream_response() -> None:
    stream = ChunkedByteStream(
        [
            chat_stream_event("开始"),
            chat_stream_event("不会读取"),
        ]
    )

    async def scenario() -> str:
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            ),
        ) as http_client:
            generator = make_openclaw_client(
                http_client
            ).stream_chat_completion(
                agent_id="web-user-123",
                openclaw_user=SNOWFLAKE_ID,
                message="你好",
            )
            first = await anext(generator)
            await generator.aclose()
            return first

    assert run_async(scenario()) == "开始"
    assert stream.closed is True


def test_chat_completion_ignores_extra_response_fields() -> None:
    async def scenario() -> str:
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                json={
                    "id": "chatcmpl-123",
                    "object": "chat.completion",
                    "created": 123456,
                    "model": "openclaw/web-user-123",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "回答内容",
                                "extra_field": "ignored",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                    "extra_top_level_field": "ignored",
                },
            ),
        ) as http_client:
            result = await make_openclaw_client(http_client).chat_completion(
                agent_id="web-user-123",
                openclaw_user=SNOWFLAKE_ID,
                message="你好",
            )
            return result.answer

    assert run_async(scenario()) == "回答内容"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, OpenClawRequestError),
        (401, OpenClawAuthenticationError),
        (403, OpenClawAuthenticationError),
        (404, OpenClawResponseError),
        (409, OpenClawConflictError),
        (413, OpenClawRequestError),
        (429, OpenClawResponseError),
        (500, OpenClawResponseError),
    ],
)
def test_chat_completion_maps_http_errors(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(
                status_code,
                json={"detail": TEST_TOKEN},
            ),
        ) as http_client:
            with pytest.raises(expected_error) as exc_info:
                await make_openclaw_client(http_client).chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )
            assert TEST_TOKEN not in str(exc_info.value)

    run_async(scenario())


def test_chat_completion_maps_runtime_owner_500_to_not_ready() -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(
                500,
                json={
                    "error": {
                        "message": (
                            "prepared model runtime owner was not committed"
                        ),
                        "type": "api_error",
                    }
                },
            ),
        ) as http_client:
            with pytest.raises(OpenClawRuntimeNotReadyError):
                await make_openclaw_client(http_client).chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )

    run_async(scenario())


def test_chat_completion_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawTimeoutError):
                await make_openclaw_client(http_client).chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )

    run_async(scenario())


def test_chat_completion_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawConnectionError):
                await make_openclaw_client(http_client).chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )

    run_async(scenario())


def test_chat_completion_rejects_invalid_json() -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(200, content=b"not-json"),
        ) as http_client:
            with pytest.raises(OpenClawResponseError):
                await make_openclaw_client(http_client).chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )

    run_async(scenario())


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": [{"message": {"content": ["unsupported"]}}]},
    ],
)
def test_chat_completion_rejects_invalid_response_shape(
    response: dict[str, object],
) -> None:
    async def scenario() -> None:
        async with make_async_client(
            lambda _request: httpx.Response(200, json=response),
        ) as http_client:
            with pytest.raises(OpenClawResponseError):
                await make_openclaw_client(http_client).chat_completion(
                    agent_id="web-user-123",
                    openclaw_user=SNOWFLAKE_ID,
                    message="你好",
                )

    run_async(scenario())


def test_ensure_agent_runtime_ready_request_and_response() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "payload": {
                    "ok": True,
                    "agentId": "web-user-123",
                    "ready": False,
                    "refreshed": True,
                    "reason": "runtime_owner_not_ready",
                    "retryAfterMs": 3000,
                },
            },
        )

    async def scenario() -> AgentRuntimeEnsureReadyResult:
        async with make_async_client(handler) as http_client:
            return await make_openclaw_client(
                http_client
            ).ensure_agent_runtime_ready(agent_id="web-user-123")

    result = run_async(scenario())

    assert len(seen_requests) == 1
    request = seen_requests[0]
    body = json.loads(request.content.decode())
    assert request.method == "POST"
    assert request.url.path == ADMIN_RPC_PATH
    assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 120.0,
        "write": 30.0,
        "pool": 10.0,
    }
    assert body == {
        "method": ENSURE_AGENT_RUNTIME_READY_METHOD,
        "params": {"agentId": "web-user-123"},
    }
    assert result.agent_id == "web-user-123"
    assert result.ready is False
    assert result.ok is True
    assert result.refreshed is True
    assert result.reason == "runtime_owner_not_ready"
    assert result.retry_after_ms == 3000


def test_ensure_agent_runtime_ready_accepts_direct_business_payload() -> None:
    async def scenario() -> AgentRuntimeEnsureReadyResult:
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                json={
                    "ok": True,
                    "agentId": "web-user-123",
                    "ready": True,
                    "refreshed": False,
                    "retryAfterMs": 0,
                },
            ),
        ) as http_client:
            return await make_openclaw_client(
                http_client
            ).ensure_agent_runtime_ready(agent_id="web-user-123")

    result = run_async(scenario())

    assert result.ok is True
    assert result.agent_id == "web-user-123"
    assert result.ready is True
    assert result.refreshed is False
    assert result.retry_after_ms == 0


@pytest.mark.parametrize(
    "response_payload",
    [
        {
            "ok": False,
            "agentId": "web-user-missing",
            "ready": False,
            "error": "agent_not_found",
        },
        {
            "ok": False,
            "agentId": "web-user-refresh-failed",
            "ready": False,
            "error": "runtime_refresh_failed",
            "retryAfterMs": 3000,
        },
    ],
)
def test_ensure_agent_runtime_ready_parses_business_failures(
    response_payload: dict[str, object],
) -> None:
    async def scenario() -> AgentRuntimeEnsureReadyResult:
        async with make_async_client(
            lambda _request: httpx.Response(
                200,
                json={"ok": True, "payload": response_payload},
            ),
        ) as http_client:
            return await make_openclaw_client(
                http_client
            ).ensure_agent_runtime_ready(
                agent_id=str(response_payload["agentId"]),
            )

    result = run_async(scenario())

    assert result.ok is False
    assert result.ready is False
    assert result.error == response_payload["error"]


@pytest.mark.parametrize(
    "agent_id",
    [
        "",
        "   ",
        "UpperCase",
        "-starts-with-dash",
        "_starts_with_underscore",
        "has.dot",
        "a" * 65,
    ],
)
def test_ensure_agent_runtime_ready_rejects_non_canonical_agent_id(
    agent_id: str,
) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    async def scenario() -> None:
        async with make_async_client(handler) as http_client:
            with pytest.raises(OpenClawRequestError):
                await make_openclaw_client(
                    http_client
                ).ensure_agent_runtime_ready(agent_id=agent_id)

    run_async(scenario())

    assert called is False
