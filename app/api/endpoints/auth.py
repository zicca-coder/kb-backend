import logging

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
logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=ApiResponse[RegisterResponse],
)
async def register(
    request: UserRegisterRequest,
    service: AuthServiceDependency,
) -> ApiResponse[RegisterResponse]:
    logger.debug(
        "进入注册接口，准备调用注册服务，username=%s, email_present=%s, "
        "phone_present=%s",
        request.username,
        request.email is not None,
        request.phone is not None,
    )
    result = await service.register(request)
    logger.debug(
        "注册服务调用完成，user_id=%s, provision_status=%s",
        result.user.id,
        result.user_agent.provision_status,
    )
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
    logger.debug(
        "进入登录接口，准备调用登录服务，account_length=%s",
        len(request.account),
    )
    result = await service.login(request)
    logger.debug(
        "登录服务调用完成，user_id=%s, expires_in=%s",
        result.user.id,
        result.expires_in,
    )
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
    logger.debug("进入获取当前用户接口，user_id=%s", current_user.id)
    user = CurrentUserResponse.model_validate(current_user)
    return success_response(data=user, detail="Get current user succeeded")
