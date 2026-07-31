from enum import StrEnum


class ProvisionStatus(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    FAILED = "failed"


SAFE_PUBLIC_PROVISION_ERROR = "Agent provisioning failed, please retry later"
