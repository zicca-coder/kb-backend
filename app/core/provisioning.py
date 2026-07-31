from enum import StrEnum


class ProvisionStatus(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    REGISTERED = "registered"
    WARMING = "warming"
    READY = "ready"
    FAILED = "failed"


SAFE_PUBLIC_PROVISION_ERROR = "Agent provisioning failed, please retry later"
DEFAULT_AGENT_RETRY_AFTER_MS = 3000
