from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.provisioning import (
    DEFAULT_AGENT_RETRY_AFTER_MS,
    ProvisionStatus,
)

AgentId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class AgentProvisionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: AgentId
    provision_status: ProvisionStatus = ProvisionStatus.REGISTERED
    agent_ready: bool = False
    requires_gateway_restart: bool = False
    retry_after_ms: int = Field(default=DEFAULT_AGENT_RETRY_AFTER_MS, ge=0)


class AgentRuntimeEnsureReadyResult(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    ok: bool
    agent_id: AgentId = Field(alias="agentId")
    ready: bool = False
    refreshed: bool = False
    reason: str | None = None
    error: str | None = None
    retry_after_ms: int = Field(default=DEFAULT_AGENT_RETRY_AFTER_MS, ge=0, alias="retryAfterMs")


class OpenClawChatResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]
