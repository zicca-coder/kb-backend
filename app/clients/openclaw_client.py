import logging
import re
from json import JSONDecodeError
from typing import Any

import httpx
from pydantic import ValidationError

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

logger = logging.getLogger(__name__)

PROVISION_PATH = "/api/internal/agent-provisioner/provision"
EXTERNAL_USER_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")


class OpenClawClient:
    def __init__(
        self,
        *,
        base_url: str,
        gateway_token: str,
        timeout_seconds: float = 20,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = self._normalize_base_url(base_url)
        self._gateway_token = self._validate_gateway_token(gateway_token)
        self._timeout_seconds = self._validate_timeout(timeout_seconds)
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
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout_seconds,
                ) as client:
                    response = await client.post(
                        PROVISION_PATH,
                        headers=self._auth_headers(),
                        json={"external_user_id": normalized_user_id},
                    )
        except httpx.TimeoutException as exc:
            raise OpenClawTimeoutError(
                "OpenClaw Gateway request timed out",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise OpenClawConnectionError(
                "Unable to connect to OpenClaw Gateway",
            ) from exc
        except httpx.RequestError as exc:
            raise OpenClawConnectionError(
                "OpenClaw Gateway request failed",
            ) from exc

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
    def _validate_timeout(timeout_seconds: float) -> float:
        if isinstance(timeout_seconds, bool):
            raise OpenClawConfigurationError(
                "OpenClaw timeout must be greater than 0",
            )
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise OpenClawConfigurationError(
                "OpenClaw timeout must be greater than 0",
            ) from exc
        if timeout <= 0:
            raise OpenClawConfigurationError(
                "OpenClaw timeout must be greater than 0",
            )
        return timeout

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

    def _request_url(self) -> str:
        return f"{self._base_url}{PROVISION_PATH}"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._gateway_token}"}

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
