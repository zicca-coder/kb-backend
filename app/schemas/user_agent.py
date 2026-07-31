from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.ids import SnowflakeId
from app.core.provisioning import (
    DEFAULT_AGENT_RETRY_AFTER_MS,
    SAFE_PUBLIC_PROVISION_ERROR,
    ProvisionStatus,
)

AgentId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
RuntimeId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ProvisionError = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
RuntimeType = Literal["shared", "container", "os_user"]


class UserAgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: SnowflakeId
    agent_id: AgentId | None = None
    runtime_type: RuntimeType = "shared"
    runtime_id: RuntimeId | None = None
    provision_status: ProvisionStatus = ProvisionStatus.PENDING
    provision_error: ProvisionError | None = None


class UserAgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: SnowflakeId | None = None
    agent_id: AgentId | None = None
    runtime_type: RuntimeType | None = None
    runtime_id: RuntimeId | None = None
    provision_status: ProvisionStatus | None = None
    provision_error: ProvisionError | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "UserAgentUpdate":
        required_fields = (
            "user_id",
            "agent_id",
            "runtime_type",
            "provision_status",
        )
        for field_name in required_fields:
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class UserAgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: SnowflakeId
    agent_id: str | None
    runtime_type: RuntimeType
    runtime_id: str | None
    provision_status: ProvisionStatus
    provision_error: str | None
    is_deleted: bool
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class UserAgentPublicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: SnowflakeId
    agent_id: str | None
    runtime_type: RuntimeType
    runtime_id: str | None
    provision_status: ProvisionStatus
    provision_error: str | None
    agent_ready: bool = False
    retry_after_ms: int | None = None
    requires_gateway_restart: bool = False
    is_deleted: bool
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime

    @model_validator(mode="after")
    def hide_internal_provision_error(self) -> "UserAgentPublicRead":
        if (
            self.provision_status == ProvisionStatus.FAILED
            and self.provision_error is not None
        ):
            self.provision_error = SAFE_PUBLIC_PROVISION_ERROR
        self.agent_ready = self.provision_status == ProvisionStatus.READY
        if self.provision_status in (
            ProvisionStatus.REGISTERED,
            ProvisionStatus.WARMING,
        ):
            self.retry_after_ms = DEFAULT_AGENT_RETRY_AFTER_MS
        return self


class UserAgentProvisionSummary(BaseModel):
    agent_id: str | None
    provision_status: ProvisionStatus
    provision_error: str | None = None
    agent_ready: bool = False
    retry_after_ms: int | None = None
    requires_gateway_restart: bool = False

    @model_validator(mode="after")
    def hide_internal_provision_error(
        self,
    ) -> "UserAgentProvisionSummary":
        if (
            self.provision_status == ProvisionStatus.FAILED
            and self.provision_error is not None
        ):
            self.provision_error = SAFE_PUBLIC_PROVISION_ERROR
        self.agent_ready = self.provision_status == ProvisionStatus.READY
        if self.provision_status in (
            ProvisionStatus.REGISTERED,
            ProvisionStatus.WARMING,
        ):
            self.retry_after_ms = DEFAULT_AGENT_RETRY_AFTER_MS
        return self


class UserAgentList(BaseModel):
    items: list[UserAgentRead]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
