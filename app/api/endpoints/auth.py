from fastapi import APIRouter

from app.api.dependencies import AuthServiceDependency, CurrentUser
from app.schemas.auth import (
    CurrentUserResponse,
    LoginResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.response import ApiResponse, success_response

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post(
    "/register",
    response_model=ApiResponse[CurrentUserResponse],
)
async def register(
    request: UserRegisterRequest,
    service: AuthServiceDependency,
) -> ApiResponse[CurrentUserResponse]:
    user = CurrentUserResponse.model_validate(
        await service.register(request)
    )
    return success_response(data=user, detail="注册成功")


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponse],
)
async def login(
    request: UserLoginRequest,
    service: AuthServiceDependency,
) -> ApiResponse[LoginResponse]:
    result = await service.login(request)
    response = LoginResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=CurrentUserResponse.model_validate(result.user),
    )
    return success_response(data=response, detail="登录成功")


@router.get(
    "/me",
    response_model=ApiResponse[CurrentUserResponse],
)
async def get_me(
    current_user: CurrentUser,
) -> ApiResponse[CurrentUserResponse]:
    user = CurrentUserResponse.model_validate(current_user)
    return success_response(data=user, detail="获取当前用户成功")
