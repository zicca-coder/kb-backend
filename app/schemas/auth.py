from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

from app.schemas.ids import SnowflakeId
from app.schemas.user import DisplayName, Phone, Username
from app.schemas.user_agent import UserAgentProvisionSummary

Password = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128),
]
LoginPassword = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128),
]
LoginAccount = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class UserRegisterRequest(BaseModel):
    """用户注册请求。"""

    model_config = ConfigDict(extra="forbid")

    username: Username
    password: Password
    display_name: DisplayName
    phone: Phone | None = None
    email: EmailStr | None = None


class UserLoginRequest(BaseModel):
    """用户登录请求。"""

    model_config = ConfigDict(extra="forbid")

    account: LoginAccount
    password: LoginPassword


class CurrentUserResponse(BaseModel):
    """认证场景下的公开用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    username: str
    display_name: str
    phone: str | None
    email: EmailStr | None
    created_at: datetime


class TokenResponse(BaseModel):
    """Access Token 响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(TokenResponse):
    """登录成功响应。"""

    user: CurrentUserResponse


class RegisterResponse(CurrentUserResponse):
    """Registration response with the user's Agent provisioning state."""

    user: CurrentUserResponse
    agent: UserAgentProvisionSummary
