from fastapi import APIRouter

from app.api.dependencies import AuthServiceDependency, CurrentUser
from app.schemas.auth import (
    CurrentUserResponse,
    LoginResponse,
    RegisterResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.response import ApiResponse, success_response

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[RegisterResponse],
)
async def register(
    request: UserRegisterRequest,
    service: AuthServiceDependency,
) -> ApiResponse[RegisterResponse]:
    result = await service.register(request)
    user = CurrentUserResponse.model_validate(result.user)
    response = RegisterResponse(
        **user.model_dump(),
        user=user,
        agent={
            "agent_id": result.user_agent.agent_id,
            "provision_status": result.user_agent.provision_status,
            "provision_error": result.user_agent.provision_error,
        },
    )
    detail = (
        "Register succeeded"
        if result.user_agent.provision_status != "failed"
        else "Register succeeded, Agent provisioning failed"
    )
    return success_response(data=response, detail=detail)


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
    return success_response(data=response, detail="Login succeeded")


@router.get(
    "/me",
    response_model=ApiResponse[CurrentUserResponse],
)
async def get_me(
    current_user: CurrentUser,
) -> ApiResponse[CurrentUserResponse]:
    user = CurrentUserResponse.model_validate(current_user)
    return success_response(data=user, detail="Get current user succeeded")
