from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

AgentId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class AgentProvisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: AgentId
