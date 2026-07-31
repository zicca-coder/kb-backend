from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.ids import SnowflakeId

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]
Phone = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=6,
        max_length=32,
        pattern=r"^\+?[0-9]{6,31}$",
    ),
]
DisplayName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class UserCreate(BaseModel):
    """创建用户请求。"""

    model_config = ConfigDict(extra="forbid")

    username: Username
    phone: Phone | None = None
    display_name: DisplayName
    email: EmailStr | None = None


class UserUpdate(BaseModel):
    """部分更新用户请求。"""

    model_config = ConfigDict(extra="forbid")

    username: Username | None = None
    phone: Phone | None = None
    display_name: DisplayName | None = None
    email: EmailStr | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "UserUpdate":
        for field_name in ("username", "display_name"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        return self


class UserRead(BaseModel):
    """公开用户响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    username: str
    phone: str | None
    display_name: str
    email: EmailStr | None
    is_deleted: bool
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class UserList(BaseModel):
    """分页用户列表响应。"""

    items: list[UserRead]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
