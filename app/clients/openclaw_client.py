import json
import logging
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, AsyncIterator

import httpx
from pydantic import ValidationError

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
    OpenClawChatResult,
)

logger = logging.getLogger(__name__)

PROVISION_PATH = "/api/internal/agent-provisioner/provision"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
ADMIN_RPC_PATH = "/api/v1/admin/rpc"
ENSURE_AGENT_RUNTIME_READY_METHOD = "agents.runtime.ensureReady"
EXTERNAL_USER_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")
CANONICAL_AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RUNTIME_NOT_READY_PATTERNS = (
    "prepared model runtime owner was not committed",
    "runtime owner",
    "runtime_not_ready",
)
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 120.0
DEFAULT_WRITE_TIMEOUT_SECONDS = 30.0
DEFAULT_POOL_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class OpenClawTimeoutConfig:
    connect: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read: float = DEFAULT_READ_TIMEOUT_SECONDS
    write: float = DEFAULT_WRITE_TIMEOUT_SECONDS
    pool: float = DEFAULT_POOL_TIMEOUT_SECONDS

    def to_httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=None,
            connect=self.connect,
            read=self.read,
            write=self.write,
            pool=self.pool,
        )


class OpenClawClient:
    def __init__(
        self,
        *,
        base_url: str,
        gateway_token: str,
        timeout_seconds: float | None = None,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
        write_timeout_seconds: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
        pool_timeout_seconds: float = DEFAULT_POOL_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = self._normalize_base_url(base_url)
        self._gateway_token = self._validate_gateway_token(gateway_token)
        self._timeout = self._build_timeout(
            timeout_seconds=timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            write_timeout_seconds=write_timeout_seconds,
            pool_timeout_seconds=pool_timeout_seconds,
        )
        self._http_client = http_client

    async def provision_agent(
        self,
        *,
        external_user_id: int | str,
    ) -> AgentProvisionResult:
        normalized_user_id = self._normalize_external_user_id(
            external_user_id,
        )
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    self._request_url(),
                    headers=self._auth_headers(),
                    json={"external_user_id": normalized_user_id},
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.post(
                        PROVISION_PATH,
                        headers=self._auth_headers(),
                        json={"external_user_id": normalized_user_id},
                    )
        except httpx.TimeoutException as exc:
            raise OpenClawTimeoutError(
                "Backend timed out while waiting for OpenClaw Gateway",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise OpenClawConnectionError(
                "Unable to connect to OpenClaw Gateway",
            ) from exc
        except httpx.RequestError as exc:
            raise OpenClawConnectionError(
                "OpenClaw Gateway request failed",
            ) from exc

        if response.status_code == 409:
            result = self._parse_conflict_response(response)
            if result is None:
                self._raise_for_status(
                    response.status_code,
                    external_user_id=normalized_user_id,
                )
                raise AssertionError("unreachable")
            logger.info(
                "OpenClaw Agent already exists, external_user_id=%s, "
                "agent_id=%s",
                normalized_user_id,
                result.agent_id,
            )
            return result

        self._raise_for_status(
            response.status_code,
            external_user_id=normalized_user_id,
        )

        result = self._parse_success_response(response)
        logger.info(
            "OpenClaw Agent provisioned, external_user_id=%s, agent_id=%s",
            normalized_user_id,
            result.agent_id,
        )
        return result

    async def chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
    ) -> OpenClawChatResult:
        normalized_agent_id = self._normalize_agent_id(agent_id)
        normalized_openclaw_user = self._normalize_openclaw_user(
            openclaw_user,
        )
        normalized_message = self._normalize_chat_message(message)
        payload = {
            "model": f"openclaw/{normalized_agent_id}",
            "user": normalized_openclaw_user,
            "messages": [
                {
                    "role": "user",
                    "content": normalized_message,
                }
            ],
            "stream": False,
        }

        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    self._chat_request_url(),
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.post(
                        CHAT_COMPLETIONS_PATH,
                        headers=self._auth_headers(),
                        json=payload,
                    )
        except httpx.TimeoutException as exc:
            raise OpenClawTimeoutError(
                "Backend timed out while waiting for OpenClaw Gateway",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise OpenClawConnectionError(
                "Unable to connect to OpenClaw Gateway",
            ) from exc
        except httpx.RequestError as exc:
            raise OpenClawConnectionError(
                "OpenClaw Gateway request failed",
            ) from exc

        self._raise_chat_status(
            response.status_code,
            agent_id=normalized_agent_id,
            response=response,
        )
        result = self._parse_chat_response(response)
        logger.info(
            "OpenClaw chat completion succeeded, agent_id=%s",
            normalized_agent_id,
        )
        return result

    async def stream_chat_completion(
        self,
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
    ) -> AsyncIterator[str]:
        normalized_agent_id = self._normalize_agent_id(agent_id)
        normalized_openclaw_user = self._normalize_openclaw_user(
            openclaw_user,
        )
        normalized_message = self._normalize_chat_message(message)
        payload = self._chat_payload(
            agent_id=normalized_agent_id,
            openclaw_user=normalized_openclaw_user,
            message=normalized_message,
            stream=True,
        )

        try:
            if self._http_client is not None:
                async with self._http_client.stream(
                    "POST",
                    self._chat_request_url(),
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=self._timeout,
                ) as response:
                    await self._raise_stream_chat_status(
                        response,
                        agent_id=normalized_agent_id,
                    )
                    async for delta in self._iter_chat_stream(response):
                        yield delta
            else:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    async with client.stream(
                        "POST",
                        CHAT_COMPLETIONS_PATH,
                        headers=self._auth_headers(),
                        json=payload,
                    ) as response:
                        await self._raise_stream_chat_status(
                            response,
                            agent_id=normalized_agent_id,
                        )
                        async for delta in self._iter_chat_stream(response):
                            yield delta
        except httpx.TimeoutException as exc:
            raise OpenClawTimeoutError(
                "Backend timed out while reading OpenClaw stream",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise OpenClawConnectionError(
                "Unable to connect to OpenClaw Gateway",
            ) from exc
        except httpx.RequestError as exc:
            raise OpenClawConnectionError(
                "OpenClaw Gateway stream request failed",
            ) from exc

    async def ensure_agent_runtime_ready(
        self,
        *,
        agent_id: str,
    ) -> AgentRuntimeEnsureReadyResult:
        normalized_agent_id = self._normalize_canonical_agent_id(agent_id)
        payload = {
            "method": ENSURE_AGENT_RUNTIME_READY_METHOD,
            "params": {"agentId": normalized_agent_id},
        }
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    self._admin_rpc_request_url(),
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.post(
                        ADMIN_RPC_PATH,
                        headers=self._auth_headers(),
                        json=payload,
                    )
        except httpx.TimeoutException as exc:
            raise OpenClawTimeoutError(
                "Backend timed out while waiting for OpenClaw Gateway",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise OpenClawConnectionError(
                "Unable to connect to OpenClaw Gateway",
            ) from exc
        except httpx.RequestError as exc:
            raise OpenClawConnectionError(
                "OpenClaw Gateway request failed",
            ) from exc

        self._raise_admin_rpc_status(
            response.status_code,
            agent_id=normalized_agent_id,
        )
        return self._parse_agent_runtime_ready_response(response)

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        if not isinstance(base_url, str):
            raise OpenClawConfigurationError(
                "OpenClaw base URL must be configured",
            )
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise OpenClawConfigurationError(
                "OpenClaw base URL must be configured",
            )
        return normalized

    @staticmethod
    def _validate_gateway_token(gateway_token: str) -> str:
        if not isinstance(gateway_token, str) or not gateway_token.strip():
            raise OpenClawConfigurationError(
                "OpenClaw Gateway token must be configured",
            )
        return gateway_token.strip()

    @staticmethod
    def _validate_timeout_component(value: float, *, name: str) -> float:
        if isinstance(value, bool):
            raise OpenClawConfigurationError(
                f"OpenClaw {name} timeout must be greater than 0",
            )
        try:
            timeout = float(value)
        except (TypeError, ValueError) as exc:
            raise OpenClawConfigurationError(
                f"OpenClaw {name} timeout must be greater than 0",
            ) from exc
        if timeout <= 0:
            raise OpenClawConfigurationError(
                f"OpenClaw {name} timeout must be greater than 0",
            )
        return timeout

    @classmethod
    def _build_timeout(
        cls,
        *,
        timeout_seconds: float | None,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        write_timeout_seconds: float,
        pool_timeout_seconds: float,
    ) -> httpx.Timeout:
        if timeout_seconds is not None:
            timeout = cls._validate_timeout_component(
                timeout_seconds,
                name="legacy",
            )
            return OpenClawTimeoutConfig(
                connect=timeout,
                read=timeout,
                write=timeout,
                pool=timeout,
            ).to_httpx_timeout()

        return OpenClawTimeoutConfig(
            connect=cls._validate_timeout_component(
                connect_timeout_seconds,
                name="connect",
            ),
            read=cls._validate_timeout_component(
                read_timeout_seconds,
                name="read",
            ),
            write=cls._validate_timeout_component(
                write_timeout_seconds,
                name="write",
            ),
            pool=cls._validate_timeout_component(
                pool_timeout_seconds,
                name="pool",
            ),
        ).to_httpx_timeout()

    @staticmethod
    def _normalize_external_user_id(external_user_id: int | str) -> str:
        message = (
            "external_user_id must be a positive integer or non-empty string"
        )
        if isinstance(external_user_id, bool):
            raise OpenClawRequestError(message)
        if isinstance(external_user_id, int):
            if external_user_id <= 0:
                raise OpenClawRequestError(message)
            return str(external_user_id)
        if isinstance(external_user_id, str):
            normalized = external_user_id.strip()
            if not EXTERNAL_USER_ID_PATTERN.fullmatch(normalized):
                raise OpenClawRequestError(message)
            return normalized
        raise OpenClawRequestError(message)

    @staticmethod
    def _normalize_agent_id(agent_id: str) -> str:
        if not isinstance(agent_id, str):
            raise OpenClawRequestError("agent_id must be a non-empty string")
        normalized = agent_id.strip()
        if not normalized:
            raise OpenClawRequestError("agent_id must be a non-empty string")
        return normalized

    @classmethod
    def _normalize_canonical_agent_id(cls, agent_id: str) -> str:
        normalized = cls._normalize_agent_id(agent_id)
        if not CANONICAL_AGENT_ID_PATTERN.fullmatch(normalized):
            raise OpenClawRequestError(
                "agent_id must be a canonical OpenClaw Agent ID",
            )
        return normalized

    @staticmethod
    def _normalize_openclaw_user(openclaw_user: str) -> str:
        if not isinstance(openclaw_user, str):
            raise OpenClawRequestError(
                "openclaw_user must be a non-empty string",
            )
        normalized = openclaw_user.strip()
        if not normalized:
            raise OpenClawRequestError(
                "openclaw_user must be a non-empty string",
            )
        return normalized

    @staticmethod
    def _normalize_chat_message(message: str) -> str:
        if not isinstance(message, str):
            raise OpenClawRequestError("message must be a non-empty string")
        normalized = message.strip()
        if not normalized:
            raise OpenClawRequestError("message must be a non-empty string")
        return normalized

    def _request_url(self) -> str:
        return f"{self._base_url}{PROVISION_PATH}"

    def _chat_request_url(self) -> str:
        return f"{self._base_url}{CHAT_COMPLETIONS_PATH}"

    def _admin_rpc_request_url(self) -> str:
        return f"{self._base_url}{ADMIN_RPC_PATH}"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._gateway_token}"}

    @staticmethod
    def _chat_payload(
        *,
        agent_id: str,
        openclaw_user: str,
        message: str,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": f"openclaw/{agent_id}",
            "user": openclaw_user,
            "messages": [
                {
                    "role": "user",
                    "content": message,
                }
            ],
            "stream": stream,
        }

    def _raise_for_status(
        self,
        status_code: int,
        *,
        external_user_id: str,
    ) -> None:
        if status_code in (200, 201):
            return
        logger.warning(
            "OpenClaw Agent provisioning failed, external_user_id=%s, "
            "status_code=%s",
            external_user_id,
            status_code,
        )
        if status_code in (401, 403):
            raise OpenClawAuthenticationError(
                "OpenClaw Gateway authentication failed",
            )
        if status_code == 409:
            raise OpenClawConflictError(
                "OpenClaw Agent configuration conflicts with the request",
            )
        if status_code in (400, 413):
            raise OpenClawRequestError(
                "OpenClaw rejected the Agent provisioning request",
            )
        if 500 <= status_code <= 599:
            raise OpenClawResponseError(
                f"OpenClaw provisioning failed with HTTP {status_code}",
            )
        raise OpenClawResponseError(
            f"OpenClaw provisioning failed with HTTP {status_code}",
        )

    def _raise_chat_status(
        self,
        status_code: int,
        *,
        agent_id: str,
        response: httpx.Response | None = None,
    ) -> None:
        if status_code == 200:
            return
        logger.warning(
            "OpenClaw chat completion failed, agent_id=%s, status_code=%s",
            agent_id,
            status_code,
        )
        if status_code in (401, 403):
            raise OpenClawAuthenticationError(
                "OpenClaw Gateway authentication failed",
            )
        if status_code == 409:
            raise OpenClawConflictError(
                "OpenClaw Agent conflicts with the chat request",
            )
        if status_code in (400, 413):
            raise OpenClawRequestError(
                "OpenClaw rejected the chat request",
            )
        if status_code == 429:
            raise OpenClawResponseError(
                "OpenClaw chat request was rate limited",
            )
        if status_code == 404:
            raise OpenClawResponseError(
                "OpenClaw Agent or chat endpoint was not found",
            )
        if 500 <= status_code <= 599:
            if (
                response is not None
                and self._response_indicates_runtime_not_ready(response)
            ):
                raise OpenClawRuntimeNotReadyError(
                    "OpenClaw Agent runtime is not ready",
                )
            raise OpenClawResponseError(
                f"OpenClaw chat failed with HTTP {status_code}",
            )
        raise OpenClawResponseError(
            f"OpenClaw chat failed with HTTP {status_code}",
        )

    async def _raise_stream_chat_status(
        self,
        response: httpx.Response,
        *,
        agent_id: str,
    ) -> None:
        if response.status_code == 200:
            return
        await response.aread()
        self._raise_chat_status(
            response.status_code,
            agent_id=agent_id,
            response=response,
        )

    def _raise_admin_rpc_status(
        self,
        status_code: int,
        *,
        agent_id: str,
    ) -> None:
        if status_code == 200:
            return
        logger.warning(
            "OpenClaw admin RPC failed, agent_id=%s, status_code=%s",
            agent_id,
            status_code,
        )
        if status_code in (401, 403):
            raise OpenClawAuthenticationError(
                "OpenClaw Gateway authentication failed",
            )
        if status_code in (400, 413):
            raise OpenClawRequestError(
                "OpenClaw rejected the admin RPC request",
            )
        if status_code == 404:
            raise OpenClawResponseError(
                "OpenClaw admin RPC endpoint was not found",
            )
        if 500 <= status_code <= 599:
            raise OpenClawResponseError(
                f"OpenClaw admin RPC failed with HTTP {status_code}",
            )
        raise OpenClawResponseError(
            f"OpenClaw admin RPC failed with HTTP {status_code}",
        )

    @staticmethod
    def _parse_success_response(
        response: httpx.Response,
    ) -> AgentProvisionResult:
        try:
            data: Any = response.json()
        except (JSONDecodeError, ValueError) as exc:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid JSON response",
            ) from exc

        if not isinstance(data, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )

        try:
            return AgentProvisionResult.model_validate(data)
        except ValidationError as exc:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            ) from exc

    @classmethod
    def _parse_conflict_response(
        cls,
        response: httpx.Response,
    ) -> AgentProvisionResult | None:
        try:
            return cls._parse_success_response(response)
        except OpenClawResponseError:
            return None

    @staticmethod
    def _parse_chat_response(
        response: httpx.Response,
    ) -> OpenClawChatResult:
        try:
            data: Any = response.json()
        except (JSONDecodeError, ValueError) as exc:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid JSON response",
            ) from exc

        if not isinstance(data, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OpenClawResponseError(
                "OpenClaw returned an empty chat response",
            )

        return OpenClawChatResult(answer=content)

    async def _iter_chat_stream(
        self,
        response: httpx.Response,
    ) -> AsyncIterator[str]:
        buffer = ""
        async for chunk in response.aiter_text():
            if not chunk:
                continue
            buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                done, deltas = self._parse_chat_stream_event(raw_event)
                if done:
                    return
                for delta in deltas:
                    yield delta

        if buffer.strip():
            done, deltas = self._parse_chat_stream_event(buffer)
            if done:
                return
            for delta in deltas:
                yield delta

    @staticmethod
    def _parse_chat_stream_event(raw_event: str) -> tuple[bool, list[str]]:
        normalized_event = raw_event.replace("\r\n", "\n").replace("\r", "\n")
        data_lines: list[str] = []
        for line in normalized_event.split("\n"):
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)

        if not data_lines:
            return False, []

        raw_data = "\n".join(data_lines)
        if raw_data == "[DONE]":
            return True, []

        try:
            data: Any = json.loads(raw_data)
        except (JSONDecodeError, ValueError) as exc:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid stream event",
            ) from exc

        if not isinstance(data, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid stream event",
            )

        error = data.get("error")
        if isinstance(error, dict):
            raise OpenClawResponseError(
                "OpenClaw stream returned an error event",
            )
        if error is not None:
            raise OpenClawResponseError(
                "OpenClaw stream returned an error event",
            )

        choices = data.get("choices")
        if not isinstance(choices, list):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid stream event",
            )

        deltas: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                raise OpenClawResponseError(
                    "OpenClaw returned an invalid stream event",
                )
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str) and content:
                    deltas.append(content)
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content:
                    deltas.append(content)

        return False, deltas

    @staticmethod
    def _parse_agent_runtime_ready_response(
        response: httpx.Response,
    ) -> AgentRuntimeEnsureReadyResult:
        try:
            data: Any = response.json()
        except (JSONDecodeError, ValueError) as exc:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid JSON response",
            ) from exc

        if not isinstance(data, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )

        data = OpenClawClient._unwrap_admin_rpc_payload(data)

        try:
            return AgentRuntimeEnsureReadyResult.model_validate(data)
        except ValidationError as exc:
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            ) from exc

    @staticmethod
    def _unwrap_admin_rpc_payload(data: dict[str, Any]) -> dict[str, Any]:
        if "payload" not in data:
            return data

        ok = data.get("ok")
        if ok is not True:
            error = data.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                detail = code if isinstance(code, str) else message
                if isinstance(detail, str) and detail:
                    raise OpenClawResponseError(
                        f"OpenClaw admin RPC failed: {detail}",
                    )
            raise OpenClawResponseError("OpenClaw admin RPC failed")

        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise OpenClawResponseError(
                "OpenClaw returned an invalid response format",
            )
        return payload

    @staticmethod
    def _response_indicates_runtime_not_ready(
        response: httpx.Response,
    ) -> bool:
        try:
            data: Any = response.json()
        except (JSONDecodeError, ValueError):
            return False

        candidates: list[str] = []
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                for key in ("message", "type", "code"):
                    value = error.get(key)
                    if isinstance(value, str):
                        candidates.append(value)
            for key in ("message", "detail", "type", "code"):
                value = data.get(key)
                if isinstance(value, str):
                    candidates.append(value)

        combined = " ".join(candidates).lower()
        return any(
            pattern in combined
            for pattern in RUNTIME_NOT_READY_PATTERNS
        )
